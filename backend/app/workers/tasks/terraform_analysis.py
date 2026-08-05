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
    FindingResolutionReason,
    IssueCategory,
    IssueSeverity,
    Repository,
    Rule,
    RuleDomain,
    ScanStatus,
    TerraformFinding,
    TerraformRoot,
    TerraformScan,
)
from app.services import state_machines as sm
from app.services.deduplication import compute_fingerprint
from app.services.opa.evaluator import OpaUnavailableError
from app.services.scoring import compute_score, score_to_grade
from app.services.terraform.hcl_parser import (
    derive_module_path,
    merge_terraform_configs,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


class TerraformFetchError(Exception):
    """Raised when Terraform files cannot be fetched from GitHub (transient)."""


def _terraform_address(
    module_path: str | None, resource_address: str | None
) -> str | None:
    """Full Terraform address for a finding, module prefix included.

    Prefixes the resource address (``aws_s3_bucket.logs``) with a single
    ``module.`` segment carrying the directory-derived module path
    (``module.modules.storage.aws_s3_bucket.logs`` for path ``modules/storage``,
    matching the spec's ``module.storage.aws_s3_bucket.logs`` shape). A single
    prefix — not one per path segment — because the path is a directory locator,
    not a resolved ``module {}`` invocation chain (see ``derive_module_path``).
    Root-module resources (no ``module_path``) get the bare resource address;
    returns ``None`` only when the rule emitted no resource address at all.
    """
    if resource_address is None:
        return None
    if not module_path:
        return resource_address
    return f"module.{module_path.replace('/', '.')}.{resource_address}"


def _resolve_stale_findings(
    session: Session, terraform_root_id: uuid.UUID, seen_fingerprints: set[str]
) -> None:
    """Resolve open findings of a root not reported by the latest scan.

    Covers findings the user fixed manually, and findings of rules that were
    removed or disabled since the previous scan. Mirrors
    static_analysis._resolve_stale_issues.
    """
    now = datetime.now(timezone.utc)
    open_findings = session.exec(
        select(TerraformFinding)
        .where(TerraformFinding.terraform_root_id == terraform_root_id)
        .where(col(TerraformFinding.resolved_at).is_(None))
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
            "Resolved %d stale terraform finding(s) for root %s",
            len(stale),
            terraform_root_id,
        )


def _run_terraform_scan_impl(
    terraform_root_id: str,
    branch: str = "",
    commit_sha: str = "",
    trigger: str = "manual",
) -> dict[str, str | int | float]:
    with Session(engine) as session:
        root = session.get(TerraformRoot, uuid.UUID(terraform_root_id))
        if not root:
            return {"status": "error", "detail": "terraform_root_not_found"}
        repo = session.get(Repository, root.repo_id)
        if not repo:
            return {"status": "error", "detail": "repository_not_found"}

        effective_branch = branch or repo.default_branch
        fetch_ref = commit_sha or branch or None

        try:
            fetched = _fetch_terraform_files(repo, root.root_path, ref=fetch_ref)
        except Exception as exc:
            logger.exception(
                "Failed to fetch terraform files for %s (%s): %s",
                repo.full_name,
                root.root_path,
                exc,
            )
            raise TerraformFetchError(str(exc)) from exc

        scan = TerraformScan(
            terraform_root_id=root.id,
            status=ScanStatus.queued,
            triggered_by=AnalysisTrigger(trigger),
            branch=effective_branch,
            commit_sha=commit_sha or None,
        )
        session.add(scan)
        session.flush()
        sm.advance(scan, sm.ScanMachine, "started")

        if not fetched:
            sm.advance(scan, sm.ScanMachine, "no_targets_found")
            scan.completed_at = datetime.now(timezone.utc)
            session.add(scan)
            session.commit()
            return {
                "status": "no_targets",
                "terraform_root_id": terraform_root_id,
                "scan_id": str(scan.id),
            }

        try:
            merged = merge_terraform_configs([(f.path, f.content) for f in fetched])
            violations = asyncio.run(_evaluate(merged))
        except Exception as exc:
            logger.exception(
                "OPA evaluation failed for terraform root %s: %s", root.root_path, exc
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
            session.commit()
            return {
                "status": "failed",
                "terraform_root_id": terraform_root_id,
                "scan_id": str(scan.id),
            }

        rule_map: dict[str, Rule] = {
            r.slug: r
            for r in session.exec(
                select(Rule)
                .where(Rule.enabled == True)  # noqa: E712
                .where(Rule.domain == RuleDomain.iac_terraform)
            ).all()
        }

        seen_fingerprints: set[str] = set()
        score_inputs: list[tuple[str, float]] = []
        finding_count = 0
        for v in violations:
            rule = rule_map.get(v.rule_slug)
            if rule is None:
                # Unlike the workflow engine, Terraform rules are always
                # DB-seeded ahead of time (TERRAFORM_INITIAL_RULES) rather
                # than auto-registered from a violation — an unrecognized
                # slug here means a rego rule shipped without its Rule row,
                # a packaging bug worth surfacing, not silently working
                # around.
                logger.warning(
                    "Terraform violation for unknown rule slug %r — no matching "
                    "Rule row (domain=iac_terraform); check TERRAFORM_INITIAL_RULES",
                    v.rule_slug,
                )
                continue
            fingerprint = compute_fingerprint(
                root.id, rule.id, v.resource_address, v.discriminator
            )
            seen_fingerprints.add(fingerprint)
            finding_count += 1
            module_path = derive_module_path(v.file_path, root.root_path)
            terraform_address = _terraform_address(module_path, v.resource_address)
            stmt = (
                pg_insert(TerraformFinding)
                .values(
                    id=uuid.uuid4(),
                    scan_id=scan.id,
                    terraform_root_id=root.id,
                    rule_id=rule.id,
                    resource_address=v.resource_address,
                    file_path=v.file_path,
                    line_start=v.line_start,
                    line_end=v.line_end,
                    module_path=module_path,
                    terraform_address=terraform_address,
                    fingerprint=fingerprint,
                    severity=IssueSeverity(v.severity),
                    category=IssueCategory(v.category),
                    message=v.message,
                    context=v.context,
                    created_at=datetime.now(timezone.utc),
                )
                .on_conflict_do_update(
                    constraint="uq_terraform_finding_root_fingerprint",
                    set_={
                        "scan_id": scan.id,
                        "severity": IssueSeverity(v.severity),
                        "file_path": v.file_path,
                        "line_start": v.line_start,
                        "line_end": v.line_end,
                        "module_path": module_path,
                        "terraform_address": terraform_address,
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
        scan.completed_at = datetime.now(timezone.utc)
        session.add(scan)
        session.commit()

        _resolve_stale_findings(session, root.id, seen_fingerprints)

        root.last_scanned_at = datetime.now(timezone.utc)
        if commit_sha:
            root.last_scanned_head_sha = commit_sha
        session.add(root)
        session.commit()

        logger.info(
            "Terraform scan complete: root=%s score=%.1f grade=%s findings=%d",
            terraform_root_id,
            score,
            grade,
            finding_count,
        )
        return {
            "status": "done",
            "terraform_root_id": terraform_root_id,
            "scan_id": str(scan.id),
            "score": round(score, 1),
            "grade": grade,
            "findings": finding_count,
        }


# How long a single root scan may hold the per-root lock before it is
# considered dead and the lock expires on its own. Mirrors
# static_analysis.ANALYSIS_LOCK_TTL_SECONDS.
SCAN_LOCK_TTL_SECONDS = 600


@celery_app.task(name="terraform_analysis.run", bind=True, max_retries=3)
def run_terraform_scan(
    self: Any,  # noqa: ANN401 — celery bound task instance
    terraform_root_id: str,
    branch: str = "",
    commit_sha: str = "",
    trigger: str = "manual",
) -> dict[str, str | int | float]:
    # Per-root lock: concurrent scans of the same root race on TerraformFinding
    # upserts and duplicate TerraformScan rows, mirroring static_analysis's
    # per-repo lock.
    lock_key = f"greensecops:lock:terraform_scan:{terraform_root_id}"
    r = redis_sync.Redis.from_url(settings.REDIS_URL)
    try:
        if not r.set(lock_key, "1", nx=True, ex=SCAN_LOCK_TTL_SECONDS):
            raise self.retry(countdown=30, max_retries=10)
        try:
            return _run_terraform_scan_impl(
                terraform_root_id=terraform_root_id,
                branch=branch,
                commit_sha=commit_sha,
                trigger=trigger,
            )
        except TerraformFetchError as exc:
            raise self.retry(exc=exc, countdown=30 * (2**self.request.retries))
        finally:
            r.delete(lock_key)
    finally:
        r.close()


def _fetch_terraform_files(
    repo: Repository, root_path: str, ref: str | None = None
) -> Any:
    """Synchronous wrapper for async GitHubAppClient.fetch_terraform_files."""
    import redis.asyncio as aioredis

    from app.services.github.app_client import GitHubAppClient

    async def _fetch() -> Any:
        r = aioredis.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call]
        try:
            client = GitHubAppClient(redis_client=r)
            return list(
                await client.fetch_terraform_files(
                    repo.installation_id, repo.full_name, root_path, ref=ref
                )
            )
        finally:
            await r.aclose()

    return asyncio.run(_fetch())


async def _evaluate(parsed_config: dict[str, Any]) -> Any:
    from app.services.opa.evaluator import evaluate_terraform

    return await evaluate_terraform(parsed_config)
