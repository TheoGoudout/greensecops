import asyncio
import logging
import uuid

import redis as redis_sync
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.db import engine
from app.models import Analysis
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.services.github.app_client import InstallationRepo
from app.workers.celery_app import celery_app
from app.workers.tasks.static_analysis import ANALYSIS_LOCK_TTL_SECONDS

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
                is_private=repo.private,
            )
            has_analysis = session.exec(
                select(Analysis.id).where(Analysis.repo_id == db_repo.id).limit(1)
            ).first()
            if has_analysis is None:
                never_analyzed.append(str(db_repo.id))
            _ensure_default_docker_target(session, db_repo.id)

    # Kick off an initial analysis for repos that have never been analyzed —
    # otherwise a fresh installation shows nothing until a push arrives.
    # A per-repo "queued" key in Redis prevents duplicate enqueues when two
    # sync tasks race (e.g. `installation` + `installation_repositories` webhooks).
    from app.workers.tasks.static_analysis import run_static_analysis

    r = redis_sync.Redis.from_url(settings.REDIS_URL)
    enqueued: list[str] = []
    try:
        for i, repo_id in enumerate(never_analyzed):
            queued_key = f"greensecops:queued:static_analysis:{repo_id}"
            try:
                already_queued = not r.set(
                    queued_key, "1", nx=True, ex=ANALYSIS_LOCK_TTL_SECONDS
                )
            except Exception:
                logger.warning(
                    "Redis unavailable for analysis enqueue dedup; enqueuing repo %s anyway",
                    repo_id,
                    exc_info=True,
                )
                already_queued = False

            if already_queued:
                logger.info(
                    "Analysis already queued for repo %s, skipping duplicate enqueue",
                    repo_id,
                )
                continue

            run_static_analysis.apply_async(
                kwargs={"repo_id": repo_id, "trigger": "manual"},
                countdown=i * 2,
            )
            enqueued.append(repo_id)
    finally:
        r.close()

    if enqueued:
        logger.info(
            "Enqueued initial analysis for %d newly synced repo(s)",
            len(enqueued),
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


def _ensure_default_docker_target(session: Session, repo_id: uuid.UUID) -> None:
    """Create the repository-root DockerTarget if the repo has none.

    Docker deliberately diverges from Terraform here. A TerraformRoot must be
    registered by hand because only the user knows which directories are
    roots; Docker files announce themselves by filename, so requiring the same
    ceremony would mean a fresh installation shows no container findings until
    someone thinks to configure one. Creating the root-path target at sync
    time is what makes findings appear on day one.

    Idempotent, and scoped to "has no targets at all" rather than "has no
    root target": a user who narrowed their setup to specific subdirectories
    must not have the repo-wide target silently reinstated on the next sync.
    """
    from app.models import DockerTarget

    existing = session.exec(
        select(DockerTarget.id).where(DockerTarget.repo_id == repo_id).limit(1)
    ).first()
    if existing is not None:
        return
    session.add(DockerTarget(repo_id=repo_id, root_path=""))
    session.commit()


def _fetch_installation_repositories(installation_id: int) -> list[InstallationRepo]:
    """Synchronous wrapper for async GitHubAppClient.list_installation_repositories."""
    import redis.asyncio as aioredis

    from app.core.config import settings
    from app.services.github.app_client import GitHubAppClient

    async def _fetch() -> list[InstallationRepo]:
        r = aioredis.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call]
        try:
            client = GitHubAppClient(redis_client=r)
            return await client.list_installation_repositories(installation_id)
        finally:
            await r.aclose()

    return asyncio.run(_fetch())
