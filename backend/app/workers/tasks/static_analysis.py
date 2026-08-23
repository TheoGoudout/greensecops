from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

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
    RuleDomain,
    UsageEngine,
    UsageMeter,
    WorkflowFile,
)
from app.services import state_machines as sm
from app.services.billing import quota as billing_quota
from app.services.billing import usage as billing_usage
from app.services.deduplication import (
    compute_content_hash,
    compute_fingerprint,
    is_duplicate,
)
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.services.scan_support import scan_lock
from app.workers.celery_app import celery_app

if TYPE_CHECKING:
    from app.services.github.app_client import WorkflowFileContent
    from app.services.opa.evaluator import OpaViolation

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
        .join(WorkflowFile, Issue.workflow_file_id == WorkflowFile.id)  # type: ignore[arg-type]
        .where(Analysis.repo_id == repo.id)
        # Fixes and PRs only ever target the default branch; feature-branch
        # issues are tracked but never auto-fixed.
        .where(WorkflowFile.branch == repo.default_branch)
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
    for row_fix, pr_state in existing_rows:
        fix_by_wf[row_fix.workflow_file_id] = row_fix
        prstate_by_wf[row_fix.workflow_file_id] = pr_state

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


def _register_rule_from_violation(
    session: Session, violation: OpaViolation
) -> Rule | None:
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
            domain=RuleDomain.workflow,
            category=category,
            severity=severity,
            title=slug.replace("_", " ").capitalize(),
            description=(violation.message or slug)[:2048],
            enabled=True,
            severity_weight=1.0,
        )
        # A slug identifies a rule only within its engine (migration 0048), so
        # the conflict target is the composite constraint. Keyed on `slug`
        # alone this silently no-opped whenever another engine already owned
        # the name, and the follow-up select below then returned *that* rule.
        .on_conflict_do_nothing(index_elements=["domain", "slug"])
    )
    session.execute(stmt)
    rule = session.exec(
        select(Rule).where(Rule.slug == slug).where(Rule.domain == RuleDomain.workflow)
    ).first()
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
    branch: str,
) -> None:
    """Reconcile workflow files that no longer exist on the analysed branch.

    Soft-deletes the row (``deleted_at``) so it drops out of the
    static-analysis view and repo grade, resolves its open issues
    (``file_removed``), and withdraws any non-terminal fix targeting it, so a
    stale ``ready``/``delivered`` fix can't later resurrect content the user
    deliberately deleted. The row itself is kept (not hard-deleted) so its
    resolved issues and analysis history stay queryable, and so a re-added path
    can be cleanly restored. Scoped to the branch that was fetched: a feature
    branch missing a file says nothing about the default branch (and vice versa).
    """
    now = datetime.now(timezone.utc)
    wf_rows = session.exec(
        select(WorkflowFile)
        .where(WorkflowFile.repo_id == repo.id)
        .where(WorkflowFile.branch == branch)
    ).all()
    resolved = 0
    superseded = 0
    deleted = 0
    for wf in wf_rows:
        if wf.path in fetched_paths:
            continue
        if wf.deleted_at is None:
            wf.deleted_at = now
            session.add(wf)
            deleted += 1
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
    if resolved or superseded or deleted:
        session.commit()
        logger.info(
            "Soft-deleted %d workflow file(s), resolved %d issue(s) and "
            "superseded %d fix(es) for deleted workflow files in repo %s",
            deleted,
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
    billable: bool = True,
) -> dict[str, str | int]:
    with Session(engine) as session:
        repo = session.get(Repository, uuid.UUID(repo_id))
        if not repo:
            return {"status": "error", "detail": "repository_not_found"}

        org_id = str(repo.org_id)
        effective_branch = branch or repo.default_branch

        # Both paths re-fetch the current workflow files from GitHub and
        # reconcile deletions; a single-file run just narrows the analysed set
        # to its own file afterwards. Re-fetching (rather than re-using the
        # stored ``raw_content``) is what keeps a deleted file from being
        # re-analysed off stale content.
        single_path: str | None = None
        if workflow_file_id:
            wf = session.get(WorkflowFile, uuid.UUID(workflow_file_id))
            if wf is None:
                return {"status": "error", "detail": "workflow_file_not_found"}
            # A single-file run analyses the row's own branch, whatever branch
            # the caller passed.
            effective_branch = wf.branch
            single_path = wf.path
            fetch_ref = commit_sha or wf.branch or None
        else:
            fetch_ref = commit_sha or branch or None

        try:
            fetched = _fetch_workflow_files(repo, ref=fetch_ref)
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

        # Workflow files deleted/renamed since the last run: soft-delete them
        # and resolve their open issues so they stop showing up as current
        # findings.
        fetched_paths = {f.path for f in fetched}
        _resolve_issues_for_missing_files(
            session, repo, fetched_paths, effective_branch
        )

        workflow_files_to_analyse: Sequence[WorkflowFile | WorkflowFileContent]
        if single_path is not None:
            # Per-file re-analysis: only the target file, using its freshly
            # fetched content. If the path is gone it was just reconciled above,
            # so there is nothing to re-analyse and no issues to regenerate.
            match = next((f for f in fetched if f.path == single_path), None)
            if match is None:
                events_pub.publish_event(ev.analysis_skipped(org_id, repo_id, ""))
                return {
                    "status": "workflow_file_removed",
                    "repo_id": repo_id,
                    "results": "[]",
                }
            workflow_files_to_analyse = [match]
        else:
            workflow_files_to_analyse = fetched

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

        results: list[dict[str, str | int | float]] = []
        batch_total_issues = 0
        batch_scores: list[float] = []
        batch_any_failed = False
        # Workflow files whose content was freshly analysed this run (a
        # duplicate-skipped file is absent): the "necessary" set to regenerate.
        changed_wf_ids: set[uuid.UUID] = set()

        # The real quota gate. The API pre-check cannot hold on its own — one
        # trigger fans out to one analysis per workflow file, and most analyses
        # arrive here from a push webhook, the polling sweep or installation
        # sync, none of which pass through an API route at all. Counting down a
        # locally-tracked budget (rather than re-querying) keeps the check off
        # the hot path while still stopping the batch at exactly the cap.
        budget = (
            billing_quota.remaining(session, None, repo.org_id, "analyses")
            if billable
            else None
        )
        quota_stopped_at: str | None = None

        for wf_src in workflow_files_to_analyse:
            if budget is not None and budget <= 0:
                # Out of allowance mid-batch: stop rather than silently
                # over-serving, and remember where so the caller can say which
                # files went unanalysed instead of reporting a clean run.
                quota_stopped_at = wf_src.path
                break

            content = (
                wf_src.raw_content
                if isinstance(wf_src, WorkflowFile)
                else wf_src.content
            )
            path = wf_src.path
            content_hash = compute_content_hash(content)

            duplicate, existing = is_duplicate(
                session, content_hash, repo.id, effective_branch
            )
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

            wf_record: WorkflowFile | None
            if isinstance(wf_src, WorkflowFile):
                wf_record = wf_src
            else:
                wf_record = session.exec(
                    select(WorkflowFile)
                    .where(WorkflowFile.repo_id == repo.id)
                    .where(WorkflowFile.branch == effective_branch)
                    .where(WorkflowFile.path == path)
                ).first()
                if wf_record is None:
                    wf_record = WorkflowFile(
                        repo_id=repo.id,
                        branch=effective_branch,
                        path=path,
                        content_hash=content_hash,
                        raw_content=content,
                    )
                    session.add(wf_record)
                else:
                    wf_record.content_hash = content_hash
                    wf_record.raw_content = content
                    # The path reappeared on its branch: clear the soft-delete
                    # marker so it shows in the static-analysis view again.
                    wf_record.deleted_at = None
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
            # Charged on creation, not completion. An in-flight analysis is
            # invisible to a concurrent quota check otherwise, so two triggers
            # arriving together would both read the old total and both pass.
            # Charged in this transaction too, so an analysis that never
            # commits leaves no phantom charge. A ``failed`` analysis still
            # counts — the compute was spent, and refunding it would make
            # failure an unlimited free retry loop.
            if billable:
                billing_usage.record_for_repo(
                    session,
                    repo=repo,
                    meter=UsageMeter.analyses,
                    engine=UsageEngine.workflow,
                    source_type="analysis",
                    source_id=analysis.id,
                    commit=False,
                )
                if budget is not None:
                    budget -= 1
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

            # Scoped to this engine, like cloud_scan/terraform_analysis/
            # docker_analysis already do. Unscoped, a workflow violation whose
            # slug is also a Terraform or cloud rule name bound to that other
            # engine's Rule row, taking its severity and weight into the score.
            rule_map: dict[str, Rule] = {
                r.slug: r
                for r in session.exec(
                    select(Rule)
                    .where(Rule.enabled == True)  # noqa: E712
                    .where(Rule.domain == RuleDomain.workflow)
                ).all()
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
                # Only the rule's own discriminator. Falling back to the line
                # number made an issue's identity move whenever its line did —
                # so inserting a blank line at the top of a workflow resolved
                # every issue in it and created replacements, losing any
                # `ignored` state and re-triggering fix generation. The other
                # three engines never key on a line for exactly this reason
                # (see compute_fingerprint); a rule that can fire twice at one
                # (job, step_index) sets a discriminator.
                fingerprint = compute_fingerprint(
                    wf_record.id, rule.id, v.job, v.step_index, v.discriminator
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
                from app.services.scoring import score_to_grade

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
        # Fixes are default-branch-only: a feature-branch analysis never queues
        # generation (the query inside is branch-gated too).
        if (
            repo.auto_fix_enabled
            and changed_wf_ids
            and effective_branch == repo.default_branch
        ):
            try:
                _auto_queue_fix_generation(
                    session, repo, org_id, changed_wf_ids=changed_wf_ids
                )
            except Exception:
                logger.exception(
                    "Auto fix generation failed after analysis: repo=%s",
                    repo_id,
                )

        if quota_stopped_at is not None:
            # Say so loudly. A run that quietly analysed four of twelve files
            # and reported "done" is worse than one that failed: the grade it
            # produces looks authoritative while covering a fraction of the
            # repo. The SSE signal is distinct from ``analysis.failed`` because
            # nothing broke and retrying will not help — only upgrading will.
            skipped = len(workflow_files_to_analyse) - len(results)
            message = (
                f"Analysis stopped after {len(results)} of "
                f"{len(workflow_files_to_analyse)} workflow files: the monthly "
                f"analysis allowance is exhausted. {skipped} file(s) were not "
                f"analysed, starting with {quota_stopped_at}."
            )
            logger.warning(
                "Quota exhausted mid-batch for repo=%s: %s", repo_id, message
            )
            events_pub.publish_event(
                ev.analysis_quota_exceeded(org_id, repo_id, "analyses", message)
            )
            return {
                "status": "quota_exceeded",
                "repo_id": repo_id,
                "analysed": len(results),
                "skipped": skipped,
                "results": str(results),
            }

        return {"status": "done", "repo_id": repo_id, "results": str(results)}


@celery_app.task(name="static_analysis.run", bind=True, max_retries=3)
def run_static_analysis(
    self: Any,  # celery bound task instance
    repo_id: str,
    branch: str = "",
    commit_sha: str = "",
    trigger: str = "manual",
    workflow_file_id: str | None = None,
    force: bool = False,
    billable: bool = True,
) -> dict[str, str | int]:
    """Run static analysis for a repository (or one of its workflow files).

    ``billable=False`` is for runs the *platform* asked for rather than the
    user: the maintenance sweeper retrying an analysis that failed transiently
    on our side. Charging for our own flakiness would be wrong, and it would
    also let a repeatedly-crashing worker eat a user's whole allowance.
    """
    # Per-repo lock: concurrent analyses of the same repo race on
    # WorkflowFile.raw_content updates and duplicate Analysis rows.
    with scan_lock(f"static_analysis:{repo_id}") as acquired:
        if not acquired:
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
                billable=billable,
            )
        except WorkflowFetchError as exc:
            # Transient GitHub failure (rate limit, network): back off and retry.
            raise self.retry(exc=exc, countdown=30 * (2**self.request.retries))


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


def _fetch_workflow_files(
    repo: Repository, ref: str | None = None
) -> list[WorkflowFileContent]:
    """Synchronous wrapper for async GitHubAppClient.fetch_workflow_files."""
    import redis.asyncio as aioredis

    from app.services.github.app_client import GitHubAppClient

    async def _fetch() -> list[WorkflowFileContent]:
        r = aioredis.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call]
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


async def _evaluate(content: str) -> list[OpaViolation]:
    from app.services.opa.evaluator import evaluate_workflow

    return await evaluate_workflow(content)
