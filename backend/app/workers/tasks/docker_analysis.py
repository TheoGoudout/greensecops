from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
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
    DockerFinding,
    DockerScan,
    DockerTarget,
    FindingResolutionReason,
    IssueCategory,
    IssueSeverity,
    Repository,
    Rule,
    RuleDomain,
    ScanStatus,
)
from app.services import state_machines as sm
from app.services.deduplication import compute_fingerprint
from app.services.docker.merge import merge_docker_files
from app.services.opa.evaluator import OpaUnavailableError
from app.services.scoring import compute_score, score_to_grade
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


class DockerFetchError(Exception):
    """Raised when Docker files cannot be fetched from GitHub (transient)."""


def _resolve_stale_findings(
    session: Session, docker_target_id: uuid.UUID, seen_fingerprints: set[str]
) -> None:
    """Resolve open findings of a target not reported by the latest scan.

    Covers findings the user fixed, and findings of rules removed or disabled
    since the previous scan. Mirrors
    terraform_analysis._resolve_stale_findings.
    """
    now = datetime.now(timezone.utc)
    open_findings = session.exec(
        select(DockerFinding)
        .where(DockerFinding.docker_target_id == docker_target_id)
        .where(col(DockerFinding.resolved_at).is_(None))
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
            "Resolved %d stale docker finding(s) for target %s",
            len(stale),
            docker_target_id,
        )


def _run_docker_scan_impl(
    docker_target_id: str,
    branch: str = "",
    commit_sha: str = "",
    trigger: str = "manual",
) -> dict[str, str | int | float]:
    with Session(engine) as session:
        target = session.get(DockerTarget, uuid.UUID(docker_target_id))
        if not target:
            return {"status": "error", "detail": "docker_target_not_found"}
        repo = session.get(Repository, target.repo_id)
        if not repo:
            return {"status": "error", "detail": "repository_not_found"}

        effective_branch = branch or repo.default_branch
        fetch_ref = commit_sha or branch or None

        try:
            fetched = _fetch_docker_files(repo, target.root_path, ref=fetch_ref)
        except Exception as exc:
            logger.exception(
                "Failed to fetch docker files for %s (%s): %s",
                repo.full_name,
                target.root_path,
                exc,
            )
            raise DockerFetchError(str(exc)) from exc

        scan = DockerScan(
            docker_target_id=target.id,
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
                "docker_target_id": docker_target_id,
                "scan_id": str(scan.id),
            }

        try:
            merged = merge_docker_files([(f.path, f.content) for f in fetched])
            violations = asyncio.run(_evaluate(merged))
        except Exception as exc:
            logger.exception(
                "OPA evaluation failed for docker target %s: %s", target.root_path, exc
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
                "docker_target_id": docker_target_id,
                "scan_id": str(scan.id),
            }

        rule_map: dict[str, Rule] = {
            r.slug: r
            for r in session.exec(
                select(Rule)
                .where(Rule.enabled == True)  # noqa: E712
                .where(Rule.domain == RuleDomain.container_docker)
            ).all()
        }

        seen_fingerprints: set[str] = set()
        # Grouped by file, not flattened: see the scoring note below.
        per_file_violations: dict[str, list[tuple[str, float]]] = defaultdict(list)
        finding_count = 0
        for v in violations:
            rule = rule_map.get(v.rule_slug)
            if rule is None:
                # Like the Terraform and cloud engines (and unlike ci_workflow,
                # which auto-registers), Docker rules are always DB-seeded
                # ahead of time. An unrecognized slug means a rego rule shipped
                # without its Rule row — a packaging bug worth surfacing, not
                # silently working around.
                logger.warning(
                    "Docker violation for unknown rule slug %r — no matching Rule "
                    "row (domain=container_docker); check DOCKER_INITIAL_RULES",
                    v.rule_slug,
                )
                continue
            fingerprint = compute_fingerprint(
                target.id, rule.id, v.file_path, v.discriminator
            )
            seen_fingerprints.add(fingerprint)
            finding_count += 1
            stmt = (
                pg_insert(DockerFinding)
                .values(
                    id=uuid.uuid4(),
                    scan_id=scan.id,
                    docker_target_id=target.id,
                    rule_id=rule.id,
                    file_path=v.file_path,
                    service_name=v.service_name,
                    stage_name=v.stage_name,
                    line_start=v.line_start,
                    line_end=v.line_end,
                    fingerprint=fingerprint,
                    severity=IssueSeverity(v.severity),
                    category=IssueCategory(v.category),
                    message=v.message,
                    context=v.context,
                    created_at=datetime.now(timezone.utc),
                )
                .on_conflict_do_update(
                    constraint="uq_docker_finding_target_fingerprint",
                    set_={
                        "scan_id": scan.id,
                        "severity": IssueSeverity(v.severity),
                        "file_path": v.file_path,
                        "service_name": v.service_name,
                        "stage_name": v.stage_name,
                        "line_start": v.line_start,
                        "line_end": v.line_end,
                        "message": v.message,
                        "context": v.context,
                        # A recurring violation reopens a resolved finding.
                        "resolved_at": None,
                        "resolution_reason": None,
                    },
                )
            )
            session.execute(stmt)
            per_file_violations[v.file_path].append((v.severity, rule.severity_weight))

        # Scored as the *mean of per-file scores*, not as one pooled total.
        #
        # This is the one place the Docker engine deliberately diverges from
        # Terraform, which passes `{}` here. A Terraform root is one logical
        # module, so pooling its violations is correct. A Docker target is N
        # independent files, and pooling makes penalties accumulate across all
        # of them: measured against this repository's own eight Docker files,
        # pooling scores 0.0 (grade F) while the per-file mean scores 69.6
        # (grade C). Every repo with more than a couple of Dockerfiles would
        # otherwise grade F, which tells the user nothing.
        #
        # compute_score already averages per-group scores — that is exactly
        # what it does for a workflow's jobs — so files simply take the place
        # jobs occupy there. Files with no findings must be included or the
        # mean is taken over offenders only and a mostly-clean target scores
        # the same as an entirely dirty one.
        score_groups: dict[str, list[tuple[str, float]]] = {
            f.path: per_file_violations.get(f.path, []) for f in fetched
        }
        score = compute_score([], score_groups)
        grade = score_to_grade(score)

        sm.advance(scan, sm.ScanMachine, "succeeded")
        scan.score = score
        scan.grade = grade
        scan.file_count = len(score_groups)
        scan.completed_at = datetime.now(timezone.utc)
        session.add(scan)
        session.commit()

        _resolve_stale_findings(session, target.id, seen_fingerprints)

        target.last_scanned_at = datetime.now(timezone.utc)
        if commit_sha:
            target.last_scanned_head_sha = commit_sha
        session.add(target)
        session.commit()

        logger.info(
            "Docker scan complete: target=%s score=%.1f grade=%s findings=%d files=%d",
            docker_target_id,
            score,
            grade,
            finding_count,
            len(score_groups),
        )
        return {
            "status": "done",
            "docker_target_id": docker_target_id,
            "scan_id": str(scan.id),
            "score": round(score, 1),
            "grade": grade,
            "findings": finding_count,
            "files": len(score_groups),
        }


# How long a single target scan may hold the per-target lock before it is
# considered dead and the lock expires on its own. Mirrors
# terraform_analysis.SCAN_LOCK_TTL_SECONDS.
SCAN_LOCK_TTL_SECONDS = 600


@celery_app.task(name="docker_analysis.run", bind=True, max_retries=3)
def run_docker_scan(
    self: Any,  # noqa: ANN401 — celery bound task instance
    docker_target_id: str,
    branch: str = "",
    commit_sha: str = "",
    trigger: str = "manual",
) -> dict[str, str | int | float]:
    # Per-target lock: concurrent scans of the same target race on
    # DockerFinding upserts and duplicate DockerScan rows.
    lock_key = f"greensecops:lock:docker_scan:{docker_target_id}"
    r = redis_sync.Redis.from_url(settings.REDIS_URL)
    try:
        if not r.set(lock_key, "1", nx=True, ex=SCAN_LOCK_TTL_SECONDS):
            raise self.retry(countdown=30, max_retries=10)
        try:
            return _run_docker_scan_impl(
                docker_target_id=docker_target_id,
                branch=branch,
                commit_sha=commit_sha,
                trigger=trigger,
            )
        except DockerFetchError as exc:
            raise self.retry(exc=exc, countdown=30 * (2**self.request.retries))
        finally:
            r.delete(lock_key)
    finally:
        r.close()


def _fetch_docker_files(
    repo: Repository, root_path: str, ref: str | None = None
) -> Any:
    """Synchronous wrapper for async GitHubAppClient.fetch_docker_files."""
    import redis.asyncio as aioredis

    from app.services.github.app_client import GitHubAppClient

    async def _fetch() -> Any:
        r = aioredis.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call]
        try:
            client = GitHubAppClient(redis_client=r)
            return list(
                await client.fetch_docker_files(
                    repo.installation_id, repo.full_name, root_path, ref=ref
                )
            )
        finally:
            await r.aclose()

    return asyncio.run(_fetch())


async def _evaluate(merged_document: dict[str, Any]) -> Any:
    from app.services.opa.evaluator import evaluate_docker

    return await evaluate_docker(merged_document)
