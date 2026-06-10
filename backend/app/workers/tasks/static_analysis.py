import logging
import uuid

from sqlmodel import Session, select

from app.core.db import engine
from app.models import (
    Analysis,
    AnalysisStatus,
    AnalysisTrigger,
    Repository,
    WorkflowFile,
)
from app.services.deduplication import compute_content_hash, is_duplicate
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="static_analysis.run", bind=True, max_retries=3)
def run_static_analysis(
    self: object,
    repo_id: str,
    branch: str = "",
    commit_sha: str = "",
    trigger: str = "manual",
) -> dict[str, str]:
    with Session(engine) as session:
        repo = session.get(Repository, uuid.UUID(repo_id))
        if not repo:
            return {"status": "error", "detail": "repository_not_found"}

        # Fetch workflow files via GitHub App (sync wrapper — Celery is sync)
        import asyncio

        import redis.asyncio as aioredis

        from app.core.config import settings
        from app.services.github.app_client import GitHubAppClient

        async def _fetch() -> list[object]:
            redis_client = aioredis.from_url(settings.REDIS_URL)
            try:
                client = GitHubAppClient(redis_client)
                return await client.fetch_workflow_files(repo.installation_id, repo.full_name)
            finally:
                await redis_client.aclose()

        workflow_files_data = asyncio.run(_fetch())

        analyses_created = []
        for wf in workflow_files_data:
            content_hash = compute_content_hash(wf.content)

            # Deduplication check
            duplicate, existing = is_duplicate(session, content_hash)
            if duplicate and existing:
                logger.info(
                    "Skipping duplicate analysis for %s (hash=%s, existing=%s)",
                    wf.path, content_hash[:8], existing.id,
                )
                analyses_created.append({"status": "skipped_duplicate", "path": wf.path})
                continue

            # Upsert WorkflowFile
            wf_record = session.exec(
                select(WorkflowFile)
                .where(WorkflowFile.repo_id == repo.id)
                .where(WorkflowFile.path == wf.path)
            ).first()
            if wf_record is None:
                wf_record = WorkflowFile(
                    repo_id=repo.id,
                    path=wf.path,
                    content_hash=content_hash,
                    raw_content=wf.content,
                )
                session.add(wf_record)
                session.flush()
            else:
                wf_record.content_hash = content_hash
                wf_record.raw_content = wf.content
                session.add(wf_record)
                session.flush()

            # Create Analysis record
            analysis = Analysis(
                repo_id=repo.id,
                workflow_file_id=wf_record.id,
                content_hash=content_hash,
                status=AnalysisStatus.pending,
                triggered_by=AnalysisTrigger(trigger),
                branch=branch or repo.default_branch,
                commit_sha=commit_sha or None,
            )
            session.add(analysis)
            session.flush()
            analyses_created.append({"status": "queued", "path": wf.path, "analysis_id": str(analysis.id)})

        session.commit()

        logger.info("Static analysis task completed for repo %s: %s", repo_id, analyses_created)
        return {"status": "completed", "repo_id": repo_id, "analyses": str(analyses_created)}
