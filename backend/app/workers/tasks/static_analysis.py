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
from app.services.deduplication import (
    compute_content_hash,
    compute_issue_fingerprint,
    is_duplicate,
)
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
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

        org_id = str(repo.org_id)

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
                events_pub.publish_event(
                    ev.analysis_skipped(org_id, repo_id, str(skipped.id))
                )
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
            events_pub.publish_event(
                ev.analysis_started(
                    org_id, repo_id, str(analysis.id), branch or repo.default_branch
                )
            )

            try:
                violations = asyncio.run(_evaluate(content))
            except Exception as exc:
                logger.exception("OPA evaluation failed for %s: %s", path, exc)
                analysis.status = AnalysisStatus.failed
                analysis.error_message = str(exc)[:2000]
                analysis.completed_at = datetime.now(timezone.utc)
                session.add(analysis)
                session.commit()
                events_pub.publish_event(
                    ev.analysis_failed(
                        org_id, repo_id, str(analysis.id), str(exc)[:200]
                    )
                )
                results.append({"path": path, "status": "failed"})
                continue

            rule_map: dict[str, Rule] = {
                r.slug: r for r in session.exec(select(Rule)).all()
            }

            workflow_score_inputs: list[tuple[str, float]] = []
            job_score_inputs: dict[str, list[tuple[str, float]]] = {}
            for v in violations:
                rule = rule_map.get(v.rule_slug)
                if rule is None:
                    logger.warning("Unknown rule slug: %s", v.rule_slug)
                    continue

                fingerprint = compute_issue_fingerprint(
                    wf_record.id, rule.id, v.job, v.step
                )
                existing_issue = session.exec(
                    select(Issue).where(
                        Issue.workflow_file_id == wf_record.id,
                        Issue.fingerprint == fingerprint,
                    )
                ).first()

                if existing_issue:
                    existing_issue.analysis_id = analysis.id
                    existing_issue.job = v.job
                    existing_issue.step = v.step
                    existing_issue.line_start = v.line_start
                    existing_issue.line_end = v.line_end
                    existing_issue.message = v.message
                    existing_issue.context = v.context
                    session.add(existing_issue)
                    issue = existing_issue
                else:
                    issue = Issue(
                        analysis_id=analysis.id,
                        workflow_file_id=wf_record.id,
                        rule_id=rule.id,
                        job=v.job,
                        step=v.step,
                        fingerprint=fingerprint,
                        severity=IssueSeverity(v.severity),
                        category=IssueCategory(v.category),
                        line_start=v.line_start,
                        line_end=v.line_end,
                        message=v.message,
                        context=v.context,
                    )
                    session.add(issue)

                pair = (v.severity, rule.severity_weight)
                if v.job is None:
                    workflow_score_inputs.append(pair)
                else:
                    job_score_inputs.setdefault(v.job, []).append(pair)

            from app.services.scoring import compute_score, score_to_grade

            score = compute_score(workflow_score_inputs, job_score_inputs)
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
            events_pub.publish_event(
                ev.analysis_completed(
                    org_id, repo_id, str(analysis.id), score, grade, len(violations)
                )
            )

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


# Seconds to wait between successive per-repo analyses, to spread out the
# read-only GitHub API calls and avoid rate-limit bursts when fanning out.
REANALYZE_STAGGER_SECONDS = 2


def _reanalyze_all_repositories_impl() -> dict[str, str | int]:
    """Enqueue a fresh static analysis for every enabled repository.

    Used when a new version ships rules: each repo is re-analysed so the new
    rules are applied and grades recomputed. This behaves like an internal
    "release" event that fans out the same per-repo analysis a webhook would,
    except ``force=True`` is required since the workflow content is unchanged
    and would otherwise be skipped as a duplicate.
    """
    with Session(engine) as session:
        repos = session.exec(
            select(Repository).where(Repository.enabled == True)  # noqa: E712
        ).all()

    for i, repo in enumerate(repos):
        run_static_analysis.apply_async(
            kwargs={
                "repo_id": str(repo.id),
                "branch": repo.default_branch,
                "trigger": AnalysisTrigger.release.value,
                "force": True,
            },
            countdown=i * REANALYZE_STAGGER_SECONDS,
        )

    logger.info("Enqueued release re-analysis for %d enabled repos", len(repos))
    return {"status": "queued", "repos": len(repos)}


@celery_app.task(name="static_analysis.reanalyze_all", bind=True)
def reanalyze_all_repositories(
    self: object,  # noqa: ARG001
) -> dict[str, str | int]:
    return _reanalyze_all_repositories_impl()


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
