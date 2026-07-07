import asyncio
import logging
import uuid

from sqlmodel import Session, select

from app import crud
from app.core.db import engine
from app.models import Analysis
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.services.github.app_client import InstallationRepo
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _sync_installation_repositories_impl(
    installation_id: int, org_id: str
) -> dict[str, str | int]:
    events_pub.publish_event(ev.installation_syncing(org_id, installation_id))

    repos = _fetch_installation_repositories(installation_id)
    org_uuid = uuid.UUID(org_id)
    never_analyzed: list[str] = []
    with Session(engine) as session:
        for repo in repos:
            db_repo = crud.upsert_repository(
                session=session,
                org_id=org_uuid,
                github_repo_id=repo.github_repo_id,
                full_name=repo.full_name,
                installation_id=installation_id,
                default_branch=repo.default_branch,
            )
            has_analysis = session.exec(
                select(Analysis.id).where(Analysis.repo_id == db_repo.id).limit(1)  # type: ignore[arg-type]
            ).first()
            if has_analysis is None:
                never_analyzed.append(str(db_repo.id))

    # Kick off an initial analysis for repos that have never been analyzed —
    # otherwise a fresh installation shows nothing until a push arrives.
    from app.workers.tasks.static_analysis import run_static_analysis

    for i, repo_id in enumerate(never_analyzed):
        run_static_analysis.apply_async(
            kwargs={"repo_id": repo_id, "trigger": "manual"},
            countdown=i * 2,
        )
    if never_analyzed:
        logger.info(
            "Enqueued initial analysis for %d newly synced repo(s)",
            len(never_analyzed),
        )
    logger.info(
        "Synced %d repositories for installation %s (org=%s)",
        len(repos),
        installation_id,
        org_id,
    )
    events_pub.publish_event(
        ev.installation_synced(org_id, installation_id, len(repos))
    )
    if repos:
        events_pub.publish_event(ev.repository_added(org_id, len(repos)))
    return {
        "status": "done",
        "installation_id": installation_id,
        "org_id": org_id,
        "synced": len(repos),
    }


@celery_app.task(bind=True, max_retries=3)
def sync_installation_repositories(
    self: object,  # noqa: ARG001
    installation_id: int,
    org_id: str,
) -> dict[str, str | int]:
    return _sync_installation_repositories_impl(installation_id, org_id)


def _fetch_installation_repositories(installation_id: int) -> list[InstallationRepo]:
    """Synchronous wrapper for async GitHubAppClient.list_installation_repositories."""
    import redis.asyncio as aioredis

    from app.core.config import settings
    from app.services.github.app_client import GitHubAppClient

    async def _fetch() -> list[InstallationRepo]:
        r = aioredis.from_url(settings.REDIS_URL)
        try:
            client = GitHubAppClient(redis_client=r)
            return await client.list_installation_repositories(installation_id)
        finally:
            await r.aclose()

    return asyncio.run(_fetch())
