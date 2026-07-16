import asyncio
import logging
import uuid
from datetime import datetime, timezone

import redis as redis_sync
from ruamel.yaml import YAML as RuamelYAML
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, col, delete, select

from app.core.config import settings
from app.core.db import engine
from app.models import (
    Analysis,
    AnalysisFailureKind,
    AnalysisStatus,
    AnalysisTrigger,
    Fix,
    FixStatus,
    Issue,
    IssueCategory,
    IssueResolutionReason,
    IssueSeverity,
    LLMProvider,
    Repository,
    Rule,
    WorkflowFile,
)
from app.services import state_machines as sm
from app.services.deduplication import (
    compute_content_hash,
    compute_issue_fingerprint,
    is_duplicate,
)
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _auto_queue_fix_generation(
    session: Session,
    repo: Repository,
    org_id: str,
    changed_wf_ids: set[uuid.UUID] | None = None,
) -> None:
    """Reconcile a repo's fixes with its latest analysis and re-deliver its PR.

    Mirrors the API-level trigger_fix_generation_for_repo but skips billing/auth.
    Only targets the latest completed analysis per workflow file.

    ``changed_wf_ids`` are the workflow files whose content was freshly analysed
    this run (a duplicate-skipped file is absent). A workflow file whose content
    did not change keeps its existing fix content (no LLM call); only changed
    files are regenerated. When nothing needs regenerating the call is a no-op,
    so it stays quiet on webhook re-runs (e.g. workflow_run) that touch nothing.

    A merged fix is left untouched (its code is already on the default branch).
    Fixes on a non-merged PR are refreshed so the open PR, once re-delivered,
    reflects exactly the current issue set — rebased onto the default branch.
    """
    from collections import defaultdict

    from app.models import PullRequest, PullRequestState
    from app.workers.tasks.fix_generation import (
        init_fix_batch,
        resolve_llm_provider,
        run_fix_generation,
    )

    changed_wf_ids = changed_wf_ids or set()

    latest_analysis_subq = (
        select(Analysis.id)
        .where(Analysis.workflow_file_id == Issue.workflow_file_id)
        .where(Analysis.repo_id == repo.id)
        .where(Analysis.status == AnalysisStatus.completed)
        .order_by(Analysis.completed_at.desc().nulls_last(), Analysis.created_at.desc())  # type: ignore[union-attr]
        .limit(1)
        .correlate(Issue)
        .scalar_subquery()
    )
    issues = session.exec(
        select(Issue)
        .join(Analysis, Issue.analysis_id == Analysis.id)  # type: ignore[arg-type]
        .where(Analysis.repo_id == repo.id)
        .where(Issue.analysis_id == latest_analysis_subq)
        .where(col(Issue.resolved_at).is_(None))
        .where(col(Issue.ignored_at).is_(None))
    ).all()

    if not issues:
        return

    by_wf_file: dict[uuid.UUID, list[Issue]] = defaultdict(list)
    for issue in issues:
        by_wf_file[issue.workflow_file_id].append(issue)  # type: ignore[index]

    wf_file_ids = list(by_wf_file)

    # Existing fix (at most one per workflow file) and the state of its PR.
    existing_rows = session.exec(
        select(Fix, PullRequest.pr_state)
        .join(PullRequest, Fix.pr_id == PullRequest.id, isouter=True)  # type: ignore[arg-type]
        .where(col(Fix.workflow_file_id).in_(wf_file_ids))
    ).all()
    fix_by_wf: dict[uuid.UUID, Fix] = {}
    prstate_by_wf: dict[uuid.UUID, object] = {}
    for existing_fix, pr_state in existing_rows:
        fix_by_wf[existing_fix.workflow_file_id] = existing_fix
        prstate_by_wf[existing_fix.workflow_file_id] = pr_state

    # Split target workflow files into ones whose current fix can be reused as-is
    # and ones that must be (re)generated.
    to_keep: list[Fix] = []
    to_generate: list[uuid.UUID] = []
    delete_ids: list[uuid.UUID] = []
    for wf_id in wf_file_ids:
        existing_fix = fix_by_wf.get(wf_id)
        if prstate_by_wf.get(wf_id) == PullRequestState.merged:
            # The fix was merged: its content is on the default branch already.
            continue
        reusable = (
            existing_fix is not None
            and bool(existing_fix.full_content)
            and existing_fix.status in (FixStatus.ready, FixStatus.delivered)
            and wf_id not in changed_wf_ids
        )
        if reusable and existing_fix is not None:
            to_keep.append(existing_fix)
        else:
            to_generate.append(wf_id)
            if existing_fix is not None:
                delete_ids.append(existing_fix.id)

    # Nothing changed that would alter the PR: leave it (and its comments) alone.
    if not to_generate:
        return

    if delete_ids:
        session.exec(delete(Fix).where(col(Fix.id).in_(delete_ids)))
    # Re-include reused fixes in the delivery set. Delivery hard-resets the PR
    # branch to base and re-applies only the fixes it is handed, so an unchanged
    # file must ride along or it would be dropped from the PR.
    for fix in to_keep:
        if fix.status != FixStatus.ready:
            sm.advance(fix, sm.FixMachine, "mark_ready")
            session.add(fix)
    session.commit()

    provider_str, model_str = resolve_llm_provider(repo)
    pending_fixes: list[Fix] = []
    for wf_id in to_generate:
        fix = Fix(
            workflow_file_id=wf_id,
            llm_provider=LLMProvider(provider_str),
            llm_model=model_str,
            status=FixStatus.pending,
        )
        session.add(fix)
        session.flush()
        for issue in by_wf_file[wf_id]:
            issue.fix_id = fix.id
            session.add(issue)
        pending_fixes.append(fix)
    session.commit()

    from app.services.events import publisher as events_pub
    from app.services.events import schemas as ev

    pending_wf_ids = {f.workflow_file_id for f in pending_fixes}
    events_pub.publish_event(
        ev.fix_generating(
            org_id,
            str(repo.id),
            fix_ids=[str(f.id) for f in pending_fixes],
            issue_ids=[
                str(i.id) for i in issues if i.workflow_file_id in pending_wf_ids
            ],
        )
    )

    batch_id = uuid.uuid4().hex
    init_fix_batch(batch_id, len(pending_wf_ids))
    for wf_id in pending_wf_ids:
        run_fix_generation.delay(
            issue_ids=[str(i.id) for i in by_wf_file[wf_id]], batch_id=batch_id
        )

    logger.info(
        "Auto-queued fix generation: repo=%s regenerated=%d reused=%d",
        repo.id,
        len(pending_fixes),
        len(to_keep),
    )


def _classify_failure(exc: BaseException) -> AnalysisFailureKind:
    """Transient (retry-worthy) vs permanent (input must change) OPA failure.

    Timeouts and network/IO errors are transient; parse/value errors (invalid
    workflow YAML, a malformed policy result) will fail identically on re-run.
    """
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return AnalysisFailureKind.transient
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return AnalysisFailureKind.permanent
    # Unknown failures default to permanent so a genuinely broken input is not
    # retried forever; an operator can still retry explicitly.
    return AnalysisFailureKind.permanent


class WorkflowFetchError(Exception):
    """Raised when workflow files cannot be fetched from GitHub (transient)."""


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


def _register_rule_from_violation(session: Session, violation: object) -> Rule | None:
    """Auto-register a Rule for a violation whose slug has no DB row yet.

    A newly shipped rego rule then works end-to-end without also having to be
    added to the seed list; previously its violations were silently dropped.
    """
    slug = violation.rule_slug
    try:
        category = IssueCategory(violation.category)
        severity = IssueSeverity(violation.severity)
    except ValueError:
        logger.warning(
            "Cannot auto-register rule %s: invalid category/severity (%s/%s)",
            slug,
            violation.category,
            violation.severity,
        )
        return None

    stmt = (
        pg_insert(Rule)
        .values(
            id=uuid.uuid4(),
            slug=slug,
            category=category,
            severity=severity,
            title=slug.replace("_", " ").capitalize(),
            description=(violation.message or slug)[:2048],
            enabled=True,
            severity_weight=1.0,
        )
        .on_conflict_do_nothing(index_elements=["slug"])
    )
    session.execute(stmt)
    rule = session.exec(select(Rule).where(Rule.slug == slug)).first()
    if rule is not None:
        logger.info("Auto-registered new rule '%s' from OPA violation", slug)
    return rule


def _resolve_stale_issues(
    session: Session,
    workflow_file_id: uuid.UUID,
    seen_fingerprints: set[str],
) -> None:
    """Resolve open issues of a workflow file not reported by the latest run.

    Covers issues the user fixed manually, and issues of rules that were
    removed or disabled since the previous analysis.
    """
    now = datetime.now(timezone.utc)
    open_issues = session.exec(
        select(Issue)
        .where(Issue.workflow_file_id == workflow_file_id)
        .where(col(Issue.resolved_at).is_(None))
    ).all()
    stale = [i for i in open_issues if i.fingerprint not in seen_fingerprints]
    for issue in stale:
        issue.resolved_at = now
        issue.resolution_reason = IssueResolutionReason.no_longer_detected
        session.add(issue)
    if stale:
        session.commit()
        logger.info(
            "Resolved %d stale issue(s) for workflow file %s",
            len(stale),
            workflow_file_id,
        )


def _resolve_issues_for_missing_files(
    session: Session,
    repo: Repository,
    fetched_paths: set[str],
) -> None:
    """Reconcile workflow files that no longer exist in the repo.

    Resolves their open issues (``file_removed``) and withdraws any
    non-terminal fix targeting them, so a stale ``ready``/``delivered`` fix
    can't later resurrect content the user deliberately deleted.
    """
    now = datetime.now(timezone.utc)
    wf_rows = session.exec(
        select(WorkflowFile).where(WorkflowFile.repo_id == repo.id)
    ).all()
    resolved = 0
    superseded = 0
    for wf in wf_rows:
        if wf.path in fetched_paths:
            continue
        open_issues = session.exec(
            select(Issue)
            .where(Issue.workflow_file_id == wf.id)
            .where(col(Issue.resolved_at).is_(None))
        ).all()
        for issue in open_issues:
            issue.resolved_at = now
            issue.resolution_reason = IssueResolutionReason.file_removed
            session.add(issue)
            resolved += 1
        if wf.fix is not None and sm.try_advance(
            wf.fix, sm.FixMachine, "supersede_deleted_file"
        ):
            session.add(wf.fix)
            superseded += 1
    if resolved or superseded:
        session.commit()
        logger.info(
            "Resolved %d issue(s) and superseded %d fix(es) for deleted "
            "workflow files in repo %s",
            resolved,
            superseded,
            repo.full_name,
        )


def _count_open_issues(session: Session, workflow_file_id: uuid.UUID | None) -> int:
    if workflow_file_id is None:
        return 0
    return len(
        session.exec(
            select(Issue)
            .where(Issue.workflow_file_id == workflow_file_id)
            .where(col(Issue.resolved_at).is_(None))
        ).all()
    )


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
        effective_branch = branch or repo.default_branch

        if workflow_file_id:
            wf = session.get(WorkflowFile, uuid.UUID(workflow_file_id))
            if wf is None:
                return {"status": "error", "detail": "workflow_file_not_found"}
            workflow_files_to_analyse: list[object] = [wf]
        else:
            try:
                workflow_files_to_analyse = _fetch_workflow_files(
                    repo, ref=commit_sha or branch or None
                )
            except Exception as exc:
                logger.exception(
                    "Failed to fetch workflow files for %s: %s", repo.full_name, exc
                )
                events_pub.publish_event(
                    ev.analysis_failed(
                        org_id,
                        repo_id,
                        "",
                        f"could not fetch workflow files: {exc}"[:200],
                    )
                )
                raise WorkflowFetchError(str(exc)) from exc

            # Workflow files deleted/renamed since the last run: resolve their
            # open issues so they stop showing up as current findings.
            fetched_paths = {f.path for f in workflow_files_to_analyse}
            _resolve_issues_for_missing_files(session, repo, fetched_paths)

        if not workflow_files_to_analyse:
            now = datetime.now(timezone.utc)
            no_wf_analysis = Analysis(
                repo_id=repo.id,
                workflow_file_id=None,
                content_hash="",
                status=AnalysisStatus.no_workflows,
                triggered_by=AnalysisTrigger(trigger),
                branch=effective_branch,
                commit_sha=commit_sha or None,
                completed_at=now,
            )
            session.add(no_wf_analysis)
            session.commit()
            events_pub.publish_event(
                ev.analysis_no_workflows(org_id, repo_id, str(no_wf_analysis.id))
            )
            return {"status": "no_workflow_files", "repo_id": repo_id, "results": "[]"}

        is_batch = workflow_file_id is None and len(workflow_files_to_analyse) > 1

        if is_batch:
            events_pub.publish_event(
                ev.analysis_started(org_id, repo_id, "", effective_branch)
            )

        results: list[dict[str, str | int]] = []
        batch_total_issues = 0
        batch_scores: list[float] = []
        batch_any_failed = False
        # Workflow files whose content was freshly analysed this run (a
        # duplicate-skipped file is absent): the "necessary" set to regenerate.
        changed_wf_ids: set[uuid.UUID] = set()

        for wf in workflow_files_to_analyse:
            content = wf.raw_content if isinstance(wf, WorkflowFile) else wf.content
            path = wf.path
            content_hash = compute_content_hash(content)

            duplicate, existing = is_duplicate(session, content_hash, repo.id)
            if not force and duplicate and existing:
                logger.info(
                    "Skipping duplicate for %s (hash=%s)", path, content_hash[:8]
                )
                # Reference the prior analysis instead of inserting a new
                # `skipped` row: webhook-heavy repos (e.g. workflow_run events)
                # would otherwise accumulate one row per CI run.
                if not is_batch:
                    events_pub.publish_event(
                        ev.analysis_skipped(org_id, repo_id, str(existing.id))
                    )
                else:
                    if existing.score is not None:
                        batch_scores.append(existing.score)
                    batch_total_issues += _count_open_issues(
                        session, existing.workflow_file_id
                    )
                results.append(
                    {
                        "path": path,
                        "status": "skipped_duplicate",
                        "analysis_id": str(existing.id),
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
                    # The path reappeared: give a fix withdrawn for its
                    # deletion a path back to `ready` instead of leaving it
                    # stranded (mirrors PR-reopen restoring a closed-PR fix).
                    if wf_record.fix is not None:
                        sm.try_advance(wf_record.fix, sm.FixMachine, "restore")
                        session.add(wf_record.fix)
                session.flush()

            analysis = Analysis(
                repo_id=repo.id,
                workflow_file_id=wf_record.id,
                content_hash=content_hash,
                status=AnalysisStatus.queued,
                triggered_by=AnalysisTrigger(trigger),
                branch=effective_branch,
                commit_sha=commit_sha or None,
            )
            session.add(analysis)
            session.flush()
            # Advance queued -> running as the worker begins OPA evaluation, so
            # a row that dies before this point is distinguishable (still
            # ``queued``) from one that hangs mid-eval (``running``).
            sm.advance(analysis, sm.AnalysisMachine, "started")
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
                sm.advance(analysis, sm.AnalysisMachine, "opa_failed")
                analysis.error_message = str(exc)[:2000]
                analysis.failure_kind = _classify_failure(exc)
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
                r.slug: r
                for r in session.exec(select(Rule).where(Rule.enabled == True)).all()  # noqa: E712
            }

            seen_fingerprints: set[str] = set()
            issue_count = 0
            workflow_score_inputs: list[tuple[str, float]] = []
            job_score_inputs: dict[str, list[tuple[str, float]]] = {}
            for v in violations:
                rule = rule_map.get(v.rule_slug)
                if rule is None:
                    rule = _register_rule_from_violation(session, v)
                    if rule is None:
                        continue
                    if not rule.enabled:
                        continue
                    rule_map[v.rule_slug] = rule
                disc = v.discriminator or (
                    str(v.line_start) if v.line_start is not None else None
                )
                fingerprint = compute_issue_fingerprint(
                    wf_record.id, rule.id, v.job, v.step_index, disc
                )
                seen_fingerprints.add(fingerprint)
                issue_count += 1
                stmt = (
                    pg_insert(Issue)
                    .values(
                        id=uuid.uuid4(),
                        analysis_id=analysis.id,
                        workflow_file_id=wf_record.id,
                        rule_id=rule.id,
                        job=v.job,
                        step=v.step,
                        step_index=v.step_index,
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
                            # A recurring violation reopens a resolved issue.
                            "resolved_at": None,
                            "resolution_reason": None,
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

            sm.advance(analysis, sm.AnalysisMachine, "opa_succeeded")
            analysis.score = score
            analysis.grade = grade
            analysis.completed_at = datetime.now(timezone.utc)
            session.add(analysis)
            session.commit()

            changed_wf_ids.add(wf_record.id)

            _resolve_stale_issues(session, wf_record.id, seen_fingerprints)

            if not is_batch:
                events_pub.publish_event(
                    ev.analysis_completed(
                        org_id, repo_id, str(analysis.id), score, grade, issue_count
                    )
                )
            else:
                batch_total_issues += issue_count
                batch_scores.append(score)

            results.append(
                {
                    "path": path,
                    "status": "completed",
                    "analysis_id": str(analysis.id),
                    "score": round(score, 1),
                    "grade": grade,
                    "issues": issue_count,
                }
            )
            logger.info(
                "Analysis complete: repo=%s path=%s score=%.1f grade=%s issues=%d",
                repo_id,
                path,
                score,
                grade,
                issue_count,
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
                from app.services.scoring import score_to_grade  # noqa: PLC0415

                avg_score = (
                    sum(batch_scores) / len(batch_scores) if batch_scores else 100.0
                )
                avg_grade = score_to_grade(avg_score)
                events_pub.publish_event(
                    ev.analysis_completed(
                        org_id,
                        repo_id,
                        "",
                        avg_score,
                        avg_grade,
                        batch_total_issues,
                    )
                )

        # Reconcile fixes and refresh the open PR for both single-file and batch
        # runs, but only when a workflow's content actually changed this run.
        # _auto_queue_fix_generation is a no-op when nothing needs regenerating.
        if repo.auto_fix_enabled and changed_wf_ids:
            try:
                _auto_queue_fix_generation(
                    session, repo, org_id, changed_wf_ids=changed_wf_ids
                )
            except Exception:
                logger.exception(
                    "Auto fix generation failed after analysis: repo=%s",
                    repo_id,
                )

        return {"status": "done", "repo_id": repo_id, "results": str(results)}


# How long a single repo analysis may hold the per-repo lock before it is
# considered dead and the lock expires on its own.
ANALYSIS_LOCK_TTL_SECONDS = 600


@celery_app.task(name="static_analysis.run", bind=True, max_retries=3)
def run_static_analysis(
    self,  # noqa: ANN001
    repo_id: str,
    branch: str = "",
    commit_sha: str = "",
    trigger: str = "manual",
    workflow_file_id: str | None = None,
    force: bool = False,
) -> dict[str, str | int]:
    # Per-repo lock: concurrent analyses of the same repo race on
    # WorkflowFile.raw_content updates and duplicate Analysis rows.
    lock_key = f"greensecops:lock:static_analysis:{repo_id}"
    r = redis_sync.Redis.from_url(settings.REDIS_URL)
    try:
        if not r.set(lock_key, "1", nx=True, ex=ANALYSIS_LOCK_TTL_SECONDS):
            # Another analysis for this repo is already running.  Layers upstream
            # (installation sync dedup) should prevent true duplicates; the retry
            # here covers legitimate concurrent webhook events.  10 × 30 s = 300 s
            # max wait — enough for any realistic analysis to complete.
            raise self.retry(countdown=30, max_retries=10)
        try:
            return _run_static_analysis_impl(
                repo_id=repo_id,
                branch=branch,
                commit_sha=commit_sha,
                trigger=trigger,
                workflow_file_id=workflow_file_id,
                force=force,
            )
        except WorkflowFetchError as exc:
            # Transient GitHub failure (rate limit, network): back off and retry.
            raise self.retry(exc=exc, countdown=30 * (2**self.request.retries))
        finally:
            r.delete(lock_key)
    finally:
        r.close()


# Seconds to wait between successive per-repo analyses, to spread out the
# read-only GitHub API calls and avoid rate-limit bursts when fanning out.
REANALYZE_STAGGER_SECONDS = 2


def _reanalyze_all_repositories_impl(force: bool = True) -> dict[str, str | int]:
    """Enqueue a fresh static analysis for every enabled repository.

    Used when a new version ships rules: each repo is re-analysed so the new
    rules are applied and grades recomputed. This behaves like an internal
    "release" event that fans out the same per-repo analysis a webhook would.
    ``force=True`` bypasses content dedup (needed when rules changed but the
    workflow content did not); the nightly reconciliation run passes
    ``force=False`` so unchanged repos stay cheap.
    """
    with Session(engine) as session:
        repos = session.exec(
            select(Repository).where(Repository.enabled == True)  # noqa: E712
        ).all()

    trigger = AnalysisTrigger.release if force else AnalysisTrigger.scheduled
    for i, repo in enumerate(repos):
        run_static_analysis.apply_async(
            kwargs={
                "repo_id": str(repo.id),
                "branch": repo.default_branch,
                "trigger": trigger.value,
                "force": force,
            },
            countdown=i * REANALYZE_STAGGER_SECONDS,
        )

    logger.info("Enqueued release re-analysis for %d enabled repos", len(repos))
    return {"status": "queued", "repos": len(repos)}


@celery_app.task(name="static_analysis.reanalyze_all", bind=True)
def reanalyze_all_repositories(
    self: object,  # noqa: ARG001
    force: bool = True,
) -> dict[str, str | int]:
    return _reanalyze_all_repositories_impl(force=force)


def _fetch_workflow_files(repo: Repository, ref: str | None = None) -> list[object]:
    """Synchronous wrapper for async GitHubAppClient.fetch_workflow_files."""
    import redis.asyncio as aioredis

    from app.services.github.app_client import GitHubAppClient

    async def _fetch() -> list[object]:
        r = aioredis.from_url(settings.REDIS_URL)
        try:
            client = GitHubAppClient(redis_client=r)
            return list(
                await client.fetch_workflow_files(
                    repo.installation_id, repo.full_name, ref=ref
                )
            )
        finally:
            await r.aclose()

    return asyncio.run(_fetch())


async def _evaluate(content: str) -> list[object]:
    from app.services.opa.evaluator import evaluate_workflow

    return await evaluate_workflow(content)
