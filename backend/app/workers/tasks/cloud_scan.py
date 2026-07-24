from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import redis as redis_sync
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import engine
from app.models import (
    AnalysisFailureKind,
    AnalysisTrigger,
    CloudAccount,
    CloudFinding,
    CloudScan,
    FindingResolutionReason,
    IssueCategory,
    IssueSeverity,
    Rule,
    RuleDomain,
    ScanStatus,
)
from app.services import state_machines as sm
from app.services.cloud.aws_collector import (
    CloudCollectionError,
    collect_account_resources,
)
from app.services.deduplication import compute_cloud_finding_fingerprint
from app.services.opa.evaluator import OpaUnavailableError
from app.services.scoring import compute_score, score_to_grade
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Fallback when an account has no regions configured yet.
_DEFAULT_REGION = "us-east-1"


def _resolve_stale_findings(
    session: Session, cloud_account_id: uuid.UUID, seen_fingerprints: set[str]
) -> None:
    """Resolve open findings of an account not reported by the latest scan.

    Mirrors terraform_analysis._resolve_stale_findings — covers resources
    that were fixed or deleted since the previous scan.
    """
    now = datetime.now(timezone.utc)
    open_findings = session.exec(
        select(CloudFinding)
        .where(CloudFinding.cloud_account_id == cloud_account_id)
        .where(col(CloudFinding.resolved_at).is_(None))
    ).all()
    stale = [f for f in open_findings if f.fingerprint not in seen_fingerprints]
    for finding in stale:
        sm.try_advance(finding, sm.FindingMachine, "resolve")
        finding.resolved_at = now
        finding.resolution_reason = FindingResolutionReason.no_longer_detected
        session.add(finding)
    if stale:
        session.commit()
        logger.info(
            "Resolved %d stale cloud finding(s) for account %s",
            len(stale),
            cloud_account_id,
        )


def _run_cloud_scan_impl(
    cloud_account_id: str,
    trigger: str = "manual",
) -> dict[str, str | int | float]:
    with Session(engine) as session:
        account = session.get(CloudAccount, uuid.UUID(cloud_account_id))
        if not account:
            return {"status": "error", "detail": "cloud_account_not_found"}

        regions = [r for r in account.regions.split(",") if r] or [_DEFAULT_REGION]

        scan = CloudScan(
            cloud_account_id=account.id,
            status=ScanStatus.queued,
            triggered_by=AnalysisTrigger(trigger),
        )
        session.add(scan)
        session.flush()
        sm.advance(scan, sm.ScanMachine, "started")

        try:
            resources = collect_account_resources(
                account.role_arn or "", account.external_id, regions
            )
            violations = asyncio.run(_evaluate(resources))
        except Exception as exc:
            logger.exception(
                "Cloud scan failed for account %s: %s", account.display_name, exc
            )
            sm.advance(scan, sm.ScanMachine, "scan_failed")
            scan.error_message = str(exc)[:2000]
            scan.failure_kind = (
                AnalysisFailureKind.transient
                if isinstance(exc, OpaUnavailableError)
                else AnalysisFailureKind.permanent
            )
            scan.completed_at = datetime.now(timezone.utc)
            session.add(scan)
            if isinstance(exc, CloudCollectionError):
                sm.try_advance(account, sm.CloudAccountMachine, "verification_failed")
                session.add(account)
            session.commit()
            return {
                "status": "failed",
                "cloud_account_id": cloud_account_id,
                "scan_id": str(scan.id),
            }

        resource_count = sum(len(v) for v in resources.values())

        rule_map: dict[str, Rule] = {
            r.slug: r
            for r in session.exec(
                select(Rule)
                .where(Rule.enabled == True)  # noqa: E712
                .where(Rule.domain == RuleDomain.cloud_aws)
            ).all()
        }

        seen_fingerprints: set[str] = set()
        score_inputs: list[tuple[str, float]] = []
        finding_count = 0
        for v in violations:
            rule = rule_map.get(v.rule_slug)
            if rule is None:
                logger.warning(
                    "Cloud violation for unknown rule slug %r — no matching "
                    "Rule row (domain=cloud_aws); check CLOUD_INITIAL_RULES",
                    v.rule_slug,
                )
                continue
            fingerprint = compute_cloud_finding_fingerprint(
                account.id, rule.id, v.resource_id, v.discriminator
            )
            seen_fingerprints.add(fingerprint)
            finding_count += 1
            stmt = (
                pg_insert(CloudFinding)
                .values(
                    id=uuid.uuid4(),
                    scan_id=scan.id,
                    cloud_account_id=account.id,
                    rule_id=rule.id,
                    resource_type=v.resource_type,
                    resource_id=v.resource_id,
                    region=v.region,
                    fingerprint=fingerprint,
                    severity=IssueSeverity(v.severity),
                    category=IssueCategory(v.category),
                    message=v.message,
                    context=v.context,
                    created_at=datetime.now(timezone.utc),
                )
                .on_conflict_do_update(
                    constraint="uq_cloud_finding_account_fingerprint",
                    set_={
                        "scan_id": scan.id,
                        "severity": IssueSeverity(v.severity),
                        "region": v.region,
                        "message": v.message,
                        "context": v.context,
                        # A recurring violation reopens a resolved finding.
                        "resolved_at": None,
                        "resolution_reason": None,
                    },
                )
            )
            session.execute(stmt)
            score_inputs.append((v.severity, rule.severity_weight))

        score = compute_score(score_inputs, {})
        grade = score_to_grade(score)

        sm.advance(scan, sm.ScanMachine, "succeeded")
        scan.score = score
        scan.grade = grade
        scan.resource_count = resource_count
        scan.completed_at = datetime.now(timezone.utc)
        session.add(scan)

        sm.try_advance(account, sm.CloudAccountMachine, "verify")
        account.last_synced_at = datetime.now(timezone.utc)
        session.add(account)
        session.commit()

        _resolve_stale_findings(session, account.id, seen_fingerprints)

        logger.info(
            "Cloud scan complete: account=%s score=%.1f grade=%s findings=%d",
            cloud_account_id,
            score,
            grade,
            finding_count,
        )
        return {
            "status": "done",
            "cloud_account_id": cloud_account_id,
            "scan_id": str(scan.id),
            "score": round(score, 1),
            "grade": grade,
            "findings": finding_count,
        }


# How long a single account scan may hold the per-account lock before it is
# considered dead and the lock expires on its own. Mirrors
# terraform_analysis.SCAN_LOCK_TTL_SECONDS.
SCAN_LOCK_TTL_SECONDS = 600


@celery_app.task(name="cloud_scan.run", bind=True, max_retries=3)
def run_cloud_scan(
    self: Any,  # noqa: ANN401 — celery bound task instance
    cloud_account_id: str,
    trigger: str = "manual",
) -> dict[str, str | int | float]:
    # Per-account lock: concurrent scans of the same account race on
    # CloudFinding upserts and duplicate CloudScan rows, mirroring
    # terraform_analysis's per-root lock.
    lock_key = f"greensecops:lock:cloud_scan:{cloud_account_id}"
    r = redis_sync.Redis.from_url(settings.REDIS_URL)
    try:
        if not r.set(lock_key, "1", nx=True, ex=SCAN_LOCK_TTL_SECONDS):
            raise self.retry(countdown=30, max_retries=10)
        try:
            return _run_cloud_scan_impl(
                cloud_account_id=cloud_account_id,
                trigger=trigger,
            )
        finally:
            r.delete(lock_key)
    finally:
        r.close()


async def _evaluate(resources: dict[str, Any]) -> Any:
    from app.services.opa.evaluator import evaluate_cloud

    return await evaluate_cloud(resources)
