import asyncio
import logging
import uuid

from sqlmodel import Session

from app import crud
from app.core.db import engine
from app.services.github.app_client import InstallationRepo
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _sync_installation_repositories_impl(
    installation_id: int, org_id: str
) -> dict[str, str | int]:
    repos = _fetch_installation_repositories(installation_id)
    org_uuid = uuid.UUID(org_id)
    with Session(engine) as session:
        for repo in repos:
            crud.upsert_repository(
                session=session,
                org_id=org_uuid,
                github_repo_id=repo.github_repo_id,
                full_name=repo.full_name,
                installation_id=installation_id,
                default_branch=repo.default_branch,
            )
    logger.info(
        "Synced %d repositories for installation %s (org=%s)",
        len(repos),
        installation_id,
        org_id,
    )
    return {
        "status": "done",
        "installation_id": installation_id,
        "org_id": org_id,
        "synced": len(repos),
    }


@celery_app.task(name="installation_sync.run", bind=True, max_retries=3)
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
