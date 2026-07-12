import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, col, select

from app.core.db import engine
from app.models import (
    Analysis,
    AnalysisStatus,
    Fix,
    FixStatus,
    PullRequest,
    PullRequestState,
    Repository,
)
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.services.state_machines import (
    AnalysisEvent,
    FixEvent,
    PullRequestEvent,
    analysis_machine,
    fix_machine,
    pull_request_machine,
)
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
    with Session(engine) as session:
        stuck_analyses = session.exec(
            select(Analysis)
            .where(
                col(Analysis.status).in_(
                    [AnalysisStatus.pending, AnalysisStatus.running]
                )
            )
            .where(Analysis.created_at < cutoff)  # type: ignore[operator]
        ).all()
        for analysis in stuck_analyses:
            analysis_machine.trigger(analysis, AnalysisEvent.swept)
            analysis.error_message = (
                "Timed out: the analysis worker was interrupted before completion"
            )
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
            fix_machine.trigger(fix, FixEvent.swept)
            fix.error_message = (
                "Timed out: the fix worker was interrupted before completion"
            )
            session.add(fix)
            swept_fixes += 1

        if swept_analyses or swept_fixes:
            session.commit()
            logger.warning(
                "Swept %d stuck analysis(es) and %d stuck fix(es) to failed",
                swept_analyses,
                swept_fixes,
            )

    return {"swept_analyses": swept_analyses, "swept_fixes": swept_fixes}


@celery_app.task(name="maintenance.sweep_stuck_states", bind=True)
def sweep_stuck_states(self: object) -> dict[str, int]:  # noqa: ARG001
    return _sweep_stuck_states_impl()


def _sync_open_pr_states_impl() -> dict[str, int]:
    """Reconcile PR state with GitHub for all fix PRs we believe are open.

    Webhooks can be missed (downtime, broker failure); without this, a PR
    merged or closed while we were away stays "open" in the UI forever.
    """
    from app.services.github.app_client import parse_pr_url

    with Session(engine) as session:
        rows = session.exec(
            select(PullRequest, Repository)
            .join(Repository, PullRequest.repo_id == Repository.id)  # type: ignore[arg-type]
            .where(PullRequest.pr_state == PullRequestState.open)
            .where(col(PullRequest.pr_url).is_not(None))
        ).all()

        targets = []
        for pr_record, repo in rows:
            parsed = parse_pr_url(pr_record.pr_url or "")
            if parsed and repo.installation_id:
                full_name, pr_number = parsed
                targets.append(
                    (pr_record.id, repo.installation_id, full_name, pr_number)
                )

        if not targets:
            return {"synced": 0, "updated": 0}

        states = asyncio.run(_fetch_pr_states(targets))

        updated = 0
        for pr_id, new_state in states.items():
            if new_state is None or new_state == PullRequestState.open:
                continue
            pr_record = session.get(PullRequest, pr_id)
            if pr_record is None:
                continue
            pr_event = (
                PullRequestEvent.merge
                if new_state == PullRequestState.merged
                else PullRequestEvent.close
            )
            if not pull_request_machine.try_trigger(pr_record, pr_event):
                continue
            pr_record.updated_at = datetime.now(timezone.utc)
            session.add(pr_record)
            updated += 1

            repo = session.get(Repository, pr_record.repo_id)
            pr_fixes = list(
                session.exec(select(Fix).where(Fix.pr_id == pr_record.id)).all()
            )
            if repo:
                events_pub.publish_event(
                    ev.pr_closed(
                        str(repo.org_id),
                        str(repo.id),
                        str(pr_fixes[0].id) if pr_fixes else str(pr_record.id),
                        pr_record.pr_url or "",
                        new_state == PullRequestState.merged,
                    )
                )

        if updated:
            session.commit()
            logger.info("PR state reconciliation updated %d PR(s)", updated)

        return {"synced": len(targets), "updated": updated}


async def _fetch_pr_states(
    targets: list,
) -> dict[object, PullRequestState | None]:
    import redis.asyncio as aioredis

    from app.core.config import settings
    from app.services.github.app_client import GitHubAppClient

    r = aioredis.from_url(settings.REDIS_URL)
    states: dict[object, PullRequestState | None] = {}
    try:
        client = GitHubAppClient(redis_client=r)
        for pr_id, installation_id, full_name, pr_number in targets:
            try:
                states[pr_id] = await client.get_pr_state(
                    installation_id, full_name, pr_number
                )
            except Exception:
                logger.warning(
                    "Failed to fetch PR state for %s#%s",
                    full_name,
                    pr_number,
                    exc_info=True,
                )
                states[pr_id] = None
    finally:
        await r.aclose()
    return states


@celery_app.task(name="maintenance.sync_open_pr_states", bind=True)
def sync_open_pr_states(self: object) -> dict[str, int]:  # noqa: ARG001
    return _sync_open_pr_states_impl()
