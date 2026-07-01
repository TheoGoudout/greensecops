import asyncio
import logging
import uuid
from datetime import datetime, timezone

from ruamel.yaml import YAML as RuamelYAML
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, select

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


def _enrich_line_numbers(violations: list, raw_content: str) -> None:
    """Populate line_start/line_end on violations using ruamel.yaml node positions."""
    ryaml = RuamelYAML()
    try:
        doc = ryaml.load(raw_content)
    except Exception:
        return
    if not isinstance(doc, dict):
        return
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        return
    for v in violations:
        if v.job is None:
            continue
        job = jobs.get(v.job)
        if job is None:
            continue
        if v.step is None:
            # Job-level: point to the job key line
            try:
                line = jobs.lc.key(v.job)[0] + 1  # ruamel lc is 0-indexed
                v.line_start = line
                v.line_end = line
            except Exception:
                pass
            continue
        # Step-level: find the step with matching 'uses'
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if uses == v.step:
                try:
                    # Point to the `uses:` key within the step, not the `-` bullet
                    line = step.lc.key("uses")[0] + 1
                except Exception:
                    try:
                        line = steps.lc.item(i)[0] + 1
                    except Exception:
                        break
                v.line_start = line
                v.line_end = line
                break


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

        is_batch = workflow_file_id is None and len(workflow_files_to_analyse) > 1
        effective_branch = branch or repo.default_branch

        if is_batch:
            events_pub.publish_event(
                ev.analysis_started(org_id, repo_id, "", effective_branch)
            )

        results: list[dict[str, str | int]] = []
        batch_total_issues = 0
        batch_last_score: float = 100.0
        batch_last_grade: str = "A"
        batch_any_failed = False

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
                    branch=effective_branch,
                    commit_sha=commit_sha or None,
                    completed_at=datetime.now(timezone.utc),
                )
                session.add(skipped)
                session.commit()
                if not is_batch:
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
                branch=effective_branch,
                commit_sha=commit_sha or None,
            )
            session.add(analysis)
            session.flush()
            if not is_batch:
                events_pub.publish_event(
                    ev.analysis_started(
                        org_id, repo_id, str(analysis.id), effective_branch
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
                if not is_batch:
                    events_pub.publish_event(
                        ev.analysis_failed(
                            org_id, repo_id, str(analysis.id), str(exc)[:200]
                        )
                    )
                else:
                    batch_any_failed = True
                results.append({"path": path, "status": "failed"})
                continue

            _enrich_line_numbers(violations, content)

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
                stmt = (
                    pg_insert(Issue)
                    .values(
                        id=uuid.uuid4(),
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
                        created_at=datetime.now(timezone.utc),
                    )
                    .on_conflict_do_update(
                        constraint="uq_issue_wf_fingerprint",
                        set_={
                            "analysis_id": analysis.id,
                            "severity": IssueSeverity(v.severity),
                            "line_start": v.line_start,
                            "line_end": v.line_end,
                            "message": v.message,
                            "context": v.context,
                        },
                    )
                )
                session.execute(stmt)
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
            session.commit()

            if not is_batch:
                events_pub.publish_event(
                    ev.analysis_completed(
                        org_id, repo_id, str(analysis.id), score, grade, len(violations)
                    )
                )
            else:
                batch_total_issues += len(violations)
                batch_last_score = score
                batch_last_grade = grade

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

        if is_batch:
            all_failed = batch_any_failed and not any(
                r.get("status") == "completed" for r in results
            )
            if all_failed:
                events_pub.publish_event(
                    ev.analysis_failed(
                        org_id, repo_id, "", "one or more workflow analyses failed"
                    )
                )
            else:
                events_pub.publish_event(
                    ev.analysis_completed(
                        org_id,
                        repo_id,
                        "",
                        batch_last_score,
                        batch_last_grade,
                        batch_total_issues,
                    )
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
