from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session

from app.core.db import engine
from app.models import (
    Category,
    CloudAccount,
    CloudFinding,
    CloudScan,
    RuleDomain,
    ScanFailureKind,
    ScanStatus,
    ScanTrigger,
    Severity,
    UsageEngine,
    UsageMeter,
)
from app.services import state_machines as sm
from app.services.billing import quota as billing_quota
from app.services.billing import usage as billing_usage
from app.services.cloud.aws_collector import (
    CloudCollectionError,
    collect_account_resources,
)
from app.services.deduplication import compute_fingerprint
from app.services.opa.evaluator import OpaUnavailableError, evaluate_cloud
from app.services.scan_support import (
    CLOUD_SCAN_LOCK_TTL_SECONDS,
    load_enabled_rules,
    resolve_stale_findings,
    scan_lock,
)
from app.services.scoring import compute_score, score_to_grade
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Fallback when an account has no regions configured yet.
_DEFAULT_REGION = "us-east-1"


def _run_cloud_scan_impl(
    cloud_account_id: str,
    trigger: str = "manual",
    billable: bool = True,
) -> dict[str, str | int | float]:
    with Session(engine) as session:
        account = session.get(CloudAccount, uuid.UUID(cloud_account_id))
        if not account:
            return {"status": "error", "detail": "cloud_account_not_found"}

        regions = [r for r in account.regions.split(",") if r] or [_DEFAULT_REGION]

        # Gate before assuming the cross-account role and calling out to AWS,
        # which is by far the expensive part of this task.
        if billable and (
            refusal := billing_quota.exhausted_message(
                session, account.org_id, engine=UsageEngine.cloud
            )
        ):
            logger.warning(
                "Cloud scan refused for account=%s: %s", cloud_account_id, refusal
            )
            return {
                "status": "quota_exceeded",
                "cloud_account_id": cloud_account_id,
                "detail": refusal,
            }

        scan = CloudScan(
            cloud_account_id=account.id,
            status=ScanStatus.queued,
            triggered_by=ScanTrigger(trigger),
        )
        session.add(scan)
        session.flush()
        sm.advance(scan, sm.ScanMachine, "started")

        # Charged up front, unlike the repo engines, because a cloud scan has
        # no cheap "nothing to look at" outcome to skip: by the time we know an
        # account is empty we have already assumed the role and walked every
        # configured region. ``repo_id`` is NULL — an AWS account belongs to the
        # org, not to any one repository.
        if billable:
            billing_usage.record_for_org(
                session,
                org_id=account.org_id,
                meter=UsageMeter.analyses,
                engine=UsageEngine.cloud,
                source_type="cloud_scan",
                source_id=scan.id,
                commit=False,
            )

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
                ScanFailureKind.transient
                if isinstance(exc, OpaUnavailableError)
                else ScanFailureKind.permanent
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

        # Every collector returns a list; the guard is so an account-level
        # scalar added later fails a test rather than the scan.
        resource_count = sum(len(v) for v in resources.values() if isinstance(v, list))

        rule_map = load_enabled_rules(session, RuleDomain.cloud_aws)

        seen_fingerprints: set[str] = set()
        score_inputs: list[tuple[str, float]] = []
        finding_count = 0
        for v in violations:
            rule = rule_map.get(v.rule_slug)
            if rule is None:
                logger.warning(
                    "Cloud violation for unknown rule slug %r — no matching "
                    "Rule row (domain=cloud_aws); the catalog is derived from "
                    "the .rego files by app.core.rule_registry",
                    v.rule_slug,
                )
                continue
            fingerprint = compute_fingerprint(
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
                    severity=Severity(v.severity),
                    category=Category(v.category),
                    message=v.message,
                    context=v.context,
                    created_at=datetime.now(timezone.utc),
                )
                .on_conflict_do_update(
                    constraint="uq_cloud_finding_account_fingerprint",
                    set_={
                        "scan_id": scan.id,
                        "severity": Severity(v.severity),
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

        resolve_stale_findings(
            session,
            CloudFinding,
            "cloud_account_id",
            account.id,
            seen_fingerprints,
            "cloud",
        )

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


@celery_app.task(name="cloud_scan.run", bind=True, max_retries=3)
def run_cloud_scan(
    self: Any,  # celery bound task instance
    cloud_account_id: str,
    trigger: str = "manual",
    billable: bool = True,
) -> dict[str, str | int | float]:
    # Per-account lock: concurrent scans of the same account race on
    # CloudFinding upserts and duplicate CloudScan rows.
    with scan_lock(
        f"cloud_scan:{cloud_account_id}", CLOUD_SCAN_LOCK_TTL_SECONDS
    ) as acquired:
        if not acquired:
            raise self.retry(countdown=30, max_retries=10)
        return _run_cloud_scan_impl(
            billable=billable,
            cloud_account_id=cloud_account_id,
            trigger=trigger,
        )


async def _evaluate(resources: dict[str, Any]) -> Any:

    return await evaluate_cloud(resources)
