import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, col, select

from app.core.db import engine
from app.models import (
    Analysis,
    AnalysisFailureKind,
    AnalysisStatus,
    CloudScan,
    DockerScan,
    DynamicAnalysisStatus,
    Fix,
    FixStatus,
    PullRequest,
    PullRequestState,
    Repository,
    ScanStatus,
    TelemetryRun,
    TerraformScan,
)
from app.services import state_machines as sm
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# How long an analysis/fix may sit in a transient state before the sweeper
# declares the worker dead and fails it (workers crashing mid-task otherwise
# leave records in `running`/`generating`/`delivering` forever).
STUCK_AFTER_MINUTES = 30


def _sweep_stuck_states_impl() -> dict[str, int]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=STUCK_AFTER_MINUTES)
    swept_analyses = 0
    swept_fixes = 0
    swept_telemetry = 0
    swept_scans = 0
    with Session(engine) as session:
        stuck_analyses = session.exec(
            select(Analysis)
            .where(
                col(Analysis.status).in_(
                    [AnalysisStatus.queued, AnalysisStatus.running]
                )
            )
            .where(Analysis.created_at < cutoff)  # type: ignore[operator]
        ).all()
        for analysis in stuck_analyses:
            sm.advance(analysis, sm.AnalysisMachine, "swept")
            analysis.error_message = (
                "Timed out: the analysis worker was interrupted before completion"
            )
            # A sweep is a transient failure (worker/broker interruption) — safe
            # to retry once the pipeline is healthy again.
            analysis.failure_kind = AnalysisFailureKind.transient
            analysis.completed_at = now
            session.add(analysis)
            swept_analyses += 1

        # Fix rows have no updated_at; created_at is a conservative proxy. A
        # genuinely in-flight task commits its final status afterwards and
        # wins the race, so a false sweep self-corrects.
        stuck_fixes = session.exec(
            select(Fix)
            .where(
                col(Fix.status).in_(
                    [FixStatus.pending, FixStatus.generating, FixStatus.delivering]
                )
            )
            .where(Fix.created_at < cutoff)  # type: ignore[operator]
        ).all()
        for fix in stuck_fixes:
            sm.advance(fix, sm.FixMachine, "swept")
            fix.error_message = (
                "Timed out: the fix worker was interrupted before completion"
            )
            session.add(fix)
            swept_fixes += 1

        # TelemetryRun has no created_at/updated_at; collected_at (set at
        # ingest) is the same kind of conservative proxy used for Fix above.
        stuck_telemetry = session.exec(
            select(TelemetryRun)
            .where(
                col(TelemetryRun.dynamic_status).in_(
                    [DynamicAnalysisStatus.queued, DynamicAnalysisStatus.running]
                )
            )
            .where(TelemetryRun.collected_at < cutoff)  # type: ignore[operator]
        ).all()
        for run in stuck_telemetry:
            sm.advance(run, sm.TelemetryMachine, "swept")
            session.add(run)
            swept_telemetry += 1

        # Scans were never swept: ScanMachine has declared a `swept` event
        # since the IaC engine landed, but nothing ever fired it, so a worker
        # crash left a DockerScan/TerraformScan/CloudScan queued or running
        # forever. Every scan table is covered here, not just the new one.
        for model in (DockerScan, TerraformScan, CloudScan):
            stuck_scans = session.exec(
                select(model)
                .where(col(model.status).in_([ScanStatus.queued, ScanStatus.running]))
                .where(model.created_at < cutoff)  # type: ignore[operator]
            ).all()
            for scan in stuck_scans:
                sm.advance(scan, sm.ScanMachine, "swept")
                scan.error_message = (
                    "Timed out: the scan worker was interrupted before completion"
                )
                scan.failure_kind = AnalysisFailureKind.transient
                session.add(scan)
                swept_scans += 1

        if swept_analyses or swept_fixes or swept_telemetry or swept_scans:
            session.commit()
            logger.warning(
                "Swept %d stuck analysis(es), %d stuck fix(es), %d stuck "
                "telemetry run(s) and %d stuck scan(s) to failed",
                swept_analyses,
                swept_fixes,
                swept_telemetry,
                swept_scans,
            )

    return {
        "swept_analyses": swept_analyses,
        "swept_fixes": swept_fixes,
        "swept_telemetry": swept_telemetry,
        "swept_scans": swept_scans,
    }


@celery_app.task(name="maintenance.sweep_stuck_states", bind=True)
def sweep_stuck_states(self: object) -> dict[str, int]:  # noqa: ARG001
    return _sweep_stuck_states_impl()


def _refresh_pr_mergeable_state_impl(repo_id: str) -> dict[str, int]:
    """Refresh mergeable_state for a repo's open fix PRs after a base push.

    GitHub sends no webhook when a push to the base branch makes an open PR
    conflicted, so conflict *visibility* would otherwise wait for the
    reconcile poller. Attribute-only: no lifecycle transition, and explicitly
    no auto-rebase/redeliver (that would overwrite or spam the PR).
    """
    import uuid as _uuid

    with Session(engine) as session:
        repo = session.get(Repository, _uuid.UUID(repo_id))
        if repo is None or not repo.installation_id:
            return {"checked": 0, "updated": 0}
        rows = list(
            session.exec(
                select(PullRequest)
                .where(PullRequest.repo_id == repo.id)
                .where(
                    col(PullRequest.pr_state).in_(
                        [PullRequestState.open, PullRequestState.draft]
                    )
                )
                .where(col(PullRequest.pr_url).is_not(None))
            ).all()
        )
        if not rows:
            return {"checked": 0, "updated": 0}

        from app.services.github.app_client import parse_pr_url

        checked = 0
        updated = 0
        for pr_record in rows:
            parsed = parse_pr_url(pr_record.pr_url or "")
            if not parsed:
                continue
            full_name, pr_number = parsed
            checked += 1
            try:
                mergeable_state = asyncio.run(
                    _fetch_pr_mergeable_state(
                        repo.installation_id, full_name, pr_number
                    )
                )
            except Exception:
                logger.warning(
                    "Failed to fetch mergeable_state for %s#%s",
                    full_name,
                    pr_number,
                    exc_info=True,
                )
                continue
            if mergeable_state is None or mergeable_state == pr_record.mergeable_state:
                continue
            pr_record.mergeable_state = mergeable_state
            pr_record.updated_at = datetime.now(timezone.utc)
            session.add(pr_record)
            session.commit()
            updated += 1
            fix = session.exec(select(Fix).where(Fix.pr_id == pr_record.id)).first()
            if fix and pr_record.pr_url:
                events_pub.publish_event(
                    ev.pr_updated(
                        str(repo.org_id),
                        str(repo.id),
                        [str(fix.id)],
                        pr_record.pr_url,
                        pr_record.pr_branch,
                    )
                )
        return {"checked": checked, "updated": updated}


async def _fetch_pr_mergeable_state(
    installation_id: int, full_name: str, pr_number: int
) -> str | None:
    import redis.asyncio as aioredis

    from app.core.config import settings
    from app.services.github.app_client import GitHubAppClient

    r = aioredis.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call]
    try:
        client = GitHubAppClient(redis_client=r)
        return await client.get_pr_mergeable_state(
            installation_id, full_name, pr_number
        )
    finally:
        await r.aclose()


@celery_app.task(name="maintenance.refresh_pr_mergeable_state", bind=True)
def refresh_pr_mergeable_state(self: object, repo_id: str) -> dict[str, int]:  # noqa: ARG001
    return _refresh_pr_mergeable_state_impl(repo_id)


# Retry a failed-transient analysis at most this many times per content hash;
# repeated failures accumulate one failed row each, so the bound terminates.
MAX_AUTO_RETRY_ATTEMPTS = 3
# Only failures younger than this window are auto-retried.
AUTO_RETRY_WINDOW_HOURS = 24
_AUTO_RETRY_DEDUP_TTL = 3600  # seconds


def _retry_transient_analyses_impl() -> dict[str, int]:
    """Re-run recent transient analysis failures (OPA timeout, network error).

    Enqueues a fresh repo/branch analysis rather than firing the machine's
    ``retry`` event on the old rows: the worker creates new Analysis rows, so
    a re-queued old row would only be swept back to ``failed``. The in-place
    ``retry`` edge stays reserved for a future per-row worker (doc §1).
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=AUTO_RETRY_WINDOW_HOURS)
    scheduled = 0
    skipped_exhausted = 0
    with Session(engine) as session:
        candidates = session.exec(
            select(Analysis, Repository)
            .join(Repository, Analysis.repo_id == Repository.id)  # type: ignore[arg-type]
            .where(Analysis.status == AnalysisStatus.failed)
            .where(Analysis.failure_kind == AnalysisFailureKind.transient)
            .where(col(Analysis.completed_at).is_not(None))
            .where(Analysis.completed_at >= cutoff)  # type: ignore[operator]
            .where(Repository.enabled)
        ).all()

        seen_targets: set[tuple[object, str]] = set()
        for analysis, repo in candidates:
            attempts = len(
                session.exec(
                    select(Analysis.id)
                    .where(Analysis.repo_id == analysis.repo_id)
                    .where(Analysis.workflow_file_id == analysis.workflow_file_id)
                    .where(Analysis.content_hash == analysis.content_hash)
                    .where(Analysis.status == AnalysisStatus.failed)
                    .where(Analysis.failure_kind == AnalysisFailureKind.transient)
                ).all()
            )
            if attempts >= MAX_AUTO_RETRY_ATTEMPTS:
                skipped_exhausted += 1
                continue
            branch = analysis.branch or repo.default_branch or "main"
            target = (repo.id, branch)
            if target in seen_targets:
                continue
            seen_targets.add(target)
            if not _try_acquire_auto_retry_slot(str(repo.id), branch):
                continue
            from app.workers.tasks.static_analysis import run_static_analysis

            # force=True: a stale *completed* analysis for the same hash would
            # otherwise dedup-skip the retry.
            run_static_analysis.delay(
                repo_id=str(repo.id),
                branch=branch,
                trigger="scheduled",
                force=True,
            )
            scheduled += 1
    if scheduled or skipped_exhausted:
        logger.info(
            "Auto-retry: scheduled %d repo/branch re-run(s), %d exhausted",
            scheduled,
            skipped_exhausted,
        )
    return {"scheduled": scheduled, "skipped_exhausted": skipped_exhausted}


def _try_acquire_auto_retry_slot(repo_id: str, branch: str) -> bool:
    """Redis dedup so hourly beats don't stack retries. Fails open."""
    import redis as redis_sync

    from app.core.config import settings

    try:
        r = redis_sync.Redis.from_url(settings.REDIS_URL)
        try:
            key = f"greensecops:queued:auto_retry:{repo_id}:{branch}"
            return bool(r.set(key, "1", nx=True, ex=_AUTO_RETRY_DEDUP_TTL))
        finally:
            r.close()
    except Exception:
        logger.warning("Redis unavailable for auto-retry dedup", exc_info=True)
        return True


@celery_app.task(name="maintenance.retry_transient_analyses", bind=True)
def retry_transient_analyses(self: object) -> dict[str, int]:  # noqa: ARG001
    return _retry_transient_analyses_impl()
