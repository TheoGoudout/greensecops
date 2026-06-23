import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlmodel import Session, select, update

from app.core.db import engine
from app.models import (
    Analysis,
    AnalysisStatus,
    AnalysisTrigger,
    Issue,
    IssueCategory,
    IssueSeverity,
    Repository,
    Rule,
    WorkflowFile,
)
from app.services.deduplication import compute_content_hash, is_duplicate
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_static_analysis_impl(
    repo_id: str,
    branch: str = "",
    commit_sha: str = "",
    trigger: str = "manual",
    workflow_file_id: str | None = None,
    force: bool = False,
) -> dict[str, str | int]:
    with Session(engine) as session:
        repo = session.get(Repository, uuid.UUID(repo_id))
        if not repo:
            return {"status": "error", "detail": "repository_not_found"}

        if workflow_file_id:
            wf_record = session.get(WorkflowFile, uuid.UUID(workflow_file_id))
            workflow_files_to_analyse = [wf_record] if wf_record else []
        else:
            workflow_files_to_analyse = _fetch_workflow_files(repo)

        results: list[dict[str, str | int]] = []
        for wf in workflow_files_to_analyse:
            content = wf.raw_content if isinstance(wf, WorkflowFile) else wf.content
            path = wf.path
            content_hash = compute_content_hash(content)

            duplicate, existing = is_duplicate(session, content_hash)
            if not force and duplicate and existing:
                logger.info(
                    "Skipping duplicate for %s (hash=%s)", path, content_hash[:8]
                )
                skipped = Analysis(
                    repo_id=repo.id,
                    workflow_file_id=existing.workflow_file_id,
                    content_hash=content_hash,
                    status=AnalysisStatus.skipped,
                    score=existing.score,
                    grade=existing.grade,
                    triggered_by=AnalysisTrigger(trigger),
                    branch=branch or repo.default_branch,
                    commit_sha=commit_sha or None,
                    completed_at=datetime.now(timezone.utc),
                )
                session.add(skipped)
                session.commit()
                results.append(
                    {
                        "path": path,
                        "status": "skipped_duplicate",
                        "analysis_id": str(skipped.id),
                    }
                )
                continue

            if isinstance(wf, WorkflowFile):
                wf_record = wf
            else:
                wf_record = session.exec(
                    select(WorkflowFile)
                    .where(WorkflowFile.repo_id == repo.id)
                    .where(WorkflowFile.path == path)
                ).first()
                if wf_record is None:
                    wf_record = WorkflowFile(
                        repo_id=repo.id,
                        path=path,
                        content_hash=content_hash,
                        raw_content=content,
                    )
                    session.add(wf_record)
                else:
                    wf_record.content_hash = content_hash
                    wf_record.raw_content = content
                    session.add(wf_record)
                session.flush()

            analysis = Analysis(
                repo_id=repo.id,
                workflow_file_id=wf_record.id,
                content_hash=content_hash,
                status=AnalysisStatus.running,
                triggered_by=AnalysisTrigger(trigger),
                branch=branch or repo.default_branch,
                commit_sha=commit_sha or None,
            )
            session.add(analysis)
            session.flush()

            try:
                violations = asyncio.run(_evaluate(content))
            except Exception as exc:
                logger.exception("OPA evaluation failed for %s: %s", path, exc)
                analysis.status = AnalysisStatus.failed
                analysis.error_message = str(exc)[:2000]
                analysis.completed_at = datetime.now(timezone.utc)
                session.add(analysis)
                session.commit()
                results.append({"path": path, "status": "failed"})
                continue

            rule_map: dict[str, Rule] = {
                r.slug: r for r in session.exec(select(Rule)).all()
            }

            score_inputs: list[tuple[str, float]] = []
            for v in violations:
                rule = rule_map.get(v.rule_slug)
                if rule is None:
                    logger.warning("Unknown rule slug: %s", v.rule_slug)
                    continue
                issue = Issue(
                    analysis_id=analysis.id,
                    rule_id=rule.id,
                    severity=IssueSeverity(v.severity),
                    category=IssueCategory(v.category),
                    line_start=v.line_start,
                    line_end=v.line_end,
                    message=v.message,
                    context=v.context,
                )
                session.add(issue)
                score_inputs.append((v.severity, rule.severity_weight))

            from app.services.scoring import compute_score, score_to_grade

            score = compute_score(score_inputs)
            grade = score_to_grade(score)

            analysis.status = AnalysisStatus.completed
            analysis.score = score
            analysis.grade = grade
            analysis.completed_at = datetime.now(timezone.utc)
            session.add(analysis)
            session.execute(
                update(WorkflowFile)
                .where(WorkflowFile.id == wf_record.id)
                .values(latest_analysis_id=analysis.id)
            )
            session.commit()

            results.append(
                {
                    "path": path,
                    "status": "completed",
                    "analysis_id": str(analysis.id),
                    "score": round(score, 1),
                    "grade": grade,
                    "issues": len(violations),
                }
            )
            logger.info(
                "Analysis complete: repo=%s path=%s score=%.1f grade=%s issues=%d",
                repo_id,
                path,
                score,
                grade,
                len(violations),
            )

        return {"status": "done", "repo_id": repo_id, "results": str(results)}


@celery_app.task(name="static_analysis.run", bind=True, max_retries=3)
def run_static_analysis(
    self: object,  # noqa: ARG001
    repo_id: str,
    branch: str = "",
    commit_sha: str = "",
    trigger: str = "manual",
    workflow_file_id: str | None = None,
    force: bool = False,
) -> dict[str, str | int]:
    return _run_static_analysis_impl(
        repo_id=repo_id,
        branch=branch,
        commit_sha=commit_sha,
        trigger=trigger,
        workflow_file_id=workflow_file_id,
        force=force,
    )


def _fetch_workflow_files(repo: Repository) -> list[object]:
    """Synchronous wrapper for async GitHubAppClient.fetch_workflow_files."""
    import redis.asyncio as aioredis

    from app.core.config import settings
    from app.services.github.app_client import GitHubAppClient

    async def _fetch() -> list[object]:
        r = aioredis.from_url(settings.REDIS_URL)
        try:
            client = GitHubAppClient(redis_client=r)
            return list(
                await client.fetch_workflow_files(repo.installation_id, repo.full_name)
            )
        finally:
            await r.aclose()

    return asyncio.run(_fetch())


async def _evaluate(content: str) -> list[object]:
    from app.services.opa.evaluator import evaluate_workflow

    return await evaluate_workflow(content)
