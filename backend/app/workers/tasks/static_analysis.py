from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, col, delete, select

from app.core.config import settings
from app.core.db import engine
from app.models import (
    Category,
    FindingResolutionReason,
    FixStatus,
    LLMProvider,
    Repository,
    Rule,
    RuleDomain,
    ScanFailureKind,
    ScanStatus,
    ScanTrigger,
    Severity,
    UsageEngine,
    UsageMeter,
    WorkflowFile,
    WorkflowFinding,
    WorkflowFix,
    WorkflowScan,
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
from app.services.workflow_sync import (
    # Re-exported: this module raised it before the sync step was extracted, and
    # callers (including the task's own retry branch) still catch it here.
    WorkflowFetchError,
    fetch_workflow_files_for_repo,
    resolve_branch_head,
    sync_workflow_files,
)
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
        select(WorkflowScan.id)
        .where(WorkflowScan.workflow_file_id == WorkflowFinding.workflow_file_id)
        .where(WorkflowScan.repo_id == repo.id)
        .where(WorkflowScan.status == ScanStatus.completed)
        .order_by(
            col(WorkflowScan.completed_at).desc().nulls_last(),
            col(WorkflowScan.created_at).desc(),
        )
        .limit(1)
        .correlate(WorkflowFinding)
        .scalar_subquery()
    )
    issues = session.exec(
        select(WorkflowFinding)
        .join(WorkflowScan, WorkflowFinding.analysis_id == WorkflowScan.id)  # type: ignore[arg-type]
        .join(WorkflowFile, WorkflowFinding.workflow_file_id == WorkflowFile.id)  # type: ignore[arg-type]
        .where(WorkflowScan.repo_id == repo.id)
        # Fixes and PRs only ever target the default branch; feature-branch
        # issues are tracked but never auto-fixed.
        .where(WorkflowFile.branch == repo.default_branch)
        .where(WorkflowFinding.analysis_id == latest_analysis_subq)
        .where(col(WorkflowFinding.resolved_at).is_(None))
        .where(col(WorkflowFinding.ignored_at).is_(None))
    ).all()

    if not issues:
        return

    by_wf_file: dict[uuid.UUID, list[WorkflowFinding]] = defaultdict(list)
    for issue in issues:
        by_wf_file[issue.workflow_file_id].append(issue)  # type: ignore[index]

    wf_file_ids = list(by_wf_file)

    # Existing fix (at most one per workflow file) and the state of its PR.
    existing_rows = session.exec(
        select(WorkflowFix, PullRequest.pr_state)
        .join(PullRequest, WorkflowFix.pr_id == PullRequest.id, isouter=True)  # type: ignore[arg-type]
        .where(col(WorkflowFix.workflow_file_id).in_(wf_file_ids))
    ).all()
    fix_by_wf: dict[uuid.UUID, WorkflowFix] = {}
    prstate_by_wf: dict[uuid.UUID, object] = {}
    for row_fix, pr_state in existing_rows:
        fix_by_wf[row_fix.workflow_file_id] = row_fix
        prstate_by_wf[row_fix.workflow_file_id] = pr_state

    # Split target workflow files into ones whose current fix can be reused as-is
    # and ones that must be (re)generated.
    to_keep: list[WorkflowFix] = []
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
        session.exec(delete(WorkflowFix).where(col(WorkflowFix.id).in_(delete_ids)))
    # Re-include reused fixes in the delivery set. Delivery hard-resets the PR
    # branch to base and re-applies only the fixes it is handed, so an unchanged
    # file must ride along or it would be dropped from the PR.
    for fix in to_keep:
        if fix.status != FixStatus.ready:
            sm.advance(fix, sm.FixMachine, "mark_ready")
            session.add(fix)
    session.commit()

    provider_str, model_str = resolve_llm_provider(repo)
    pending_fixes: list[WorkflowFix] = []
    for wf_id in to_generate:
        fix = WorkflowFix(
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


def _classify_failure(exc: BaseException) -> ScanFailureKind:
    """Transient (retry-worthy) vs permanent (input must change) OPA failure.

    Timeouts and network/IO errors are transient; parse/value errors (invalid
    workflow YAML, a malformed policy result) will fail identically on re-run.
    """
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return ScanFailureKind.transient
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return ScanFailureKind.permanent
    # Unknown failures default to permanent so a genuinely broken input is not
    # retried forever; an operator can still retry explicitly.
    return ScanFailureKind.permanent


def _register_rule_from_violation(
    session: Session, violation: OpaViolation
) -> Rule | None:
    """Auto-register a Rule for a violation whose slug has no DB row yet.

    A newly shipped rego rule then works end-to-end without also having to be
    added to the seed list; previously its violations were silently dropped.
    """
    slug = violation.rule_slug
    try:
        category = Category(violation.category)
        severity = Severity(violation.severity)
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
            domain=RuleDomain.ci_workflow,
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
        select(Rule)
        .where(Rule.slug == slug)
        .where(Rule.domain == RuleDomain.ci_workflow)
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
        select(WorkflowFinding)
        .where(WorkflowFinding.workflow_file_id == workflow_file_id)
        .where(col(WorkflowFinding.resolved_at).is_(None))
    ).all()
    stale = [i for i in open_issues if i.fingerprint not in seen_fingerprints]
    for issue in stale:
        issue.resolved_at = now
        issue.resolution_reason = FindingResolutionReason.no_longer_detected
        session.add(issue)
    if stale:
        session.commit()
        logger.info(
            "Resolved %d stale issue(s) for workflow file %s",
            len(stale),
            workflow_file_id,
        )


def _count_open_issues(session: Session, workflow_file_id: uuid.UUID | None) -> int:
    if workflow_file_id is None:
        return 0
    return len(
        session.exec(
            select(WorkflowFinding)
            .where(WorkflowFinding.workflow_file_id == workflow_file_id)
            .where(col(WorkflowFinding.resolved_at).is_(None))
        ).all()
    )


@dataclass(frozen=True)
class _RunContext:
    """What every workflow file in one run sees, and none of them changes."""

    repo: Repository
    repo_id: str
    org_id: str
    effective_branch: str
    trigger: str
    commit_sha: str
    force: bool
    is_batch: bool
    billable: bool
    # Collected once per run rather than per file — see _collect_action_metadata.
    action_metadata: Mapping[str, Mapping[str, Any]]


@dataclass
class _Tally:
    """What accumulates across a run's workflow files.

    These were seven locals mutated inside a 265-line loop body. Naming them as
    one object is most of why that body could be lifted out at all: the contract
    between the loop and each file is now a signature rather than a closure.
    """

    results: list[dict[str, str | int | float]] = field(default_factory=list)
    batch_scores: list[float] = field(default_factory=list)
    changed_wf_ids: set[uuid.UUID] = field(default_factory=set)
    batch_total_issues: int = 0
    batch_any_failed: bool = False
    # Remaining `analyses` allowance, or None when the run is not billable.
    budget: int | None = None
    # Path the run stopped at when the allowance ran out mid-batch.
    quota_stopped_at: str | None = None


def _analyse_one_workflow_file(
    session: Session,
    ctx: _RunContext,
    path: str,
    content: str,
    wf_record: WorkflowFile,
    tally: _Tally,
) -> None:
    """Analyse one workflow file, recording its outcome on ``tally``.

    Was the body of the loop in ``_run_static_analysis_impl``, which ran to 464
    lines. Everything it needs from the run is on ``ctx``; everything it
    contributes goes on ``tally``.

    ``content`` and ``wf_record`` come from the sync that ran before this, and
    persisting them is *its* job — this used to upsert the row itself, below the
    duplicate check, which is exactly why a dedup-skipped file's stored copy
    went stale.
    """
    content_hash = compute_content_hash(content)

    duplicate, existing = is_duplicate(
        session, content_hash, ctx.repo.id, ctx.effective_branch
    )
    if not ctx.force and duplicate and existing:
        logger.info("Skipping duplicate for %s (hash=%s)", path, content_hash[:8])
        # Reference the prior analysis instead of inserting a new
        # `skipped` row: webhook-heavy repos (e.g. workflow_run events)
        # would otherwise accumulate one row per CI run.
        if not ctx.is_batch:
            events_pub.publish_event(
                ev.analysis_skipped(ctx.org_id, ctx.repo_id, str(existing.id))
            )
        else:
            if existing.score is not None:
                tally.batch_scores.append(existing.score)
            tally.batch_total_issues += _count_open_issues(
                session, existing.workflow_file_id
            )
        tally.results.append(
            {
                "path": path,
                "status": "skipped_duplicate",
                "analysis_id": str(existing.id),
            }
        )
        return

    analysis = WorkflowScan(
        repo_id=ctx.repo.id,
        workflow_file_id=wf_record.id,
        content_hash=content_hash,
        status=ScanStatus.queued,
        triggered_by=ScanTrigger(ctx.trigger),
        branch=ctx.effective_branch,
        commit_sha=ctx.commit_sha or None,
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
    if ctx.billable:
        billing_usage.record_for_repo(
            session,
            repo=ctx.repo,
            meter=UsageMeter.analyses,
            engine=UsageEngine.workflow,
            source_type="analysis",
            source_id=analysis.id,
            commit=False,
        )
        if tally.budget is not None:
            tally.budget -= 1
    # Advance queued -> running as the worker begins OPA evaluation, so
    # a row that dies before this point is distinguishable (still
    # ``queued``) from one that hangs mid-eval (``running``).
    sm.advance(analysis, sm.ScanMachine, "started")
    if not ctx.is_batch:
        events_pub.publish_event(
            ev.analysis_started(
                ctx.org_id, ctx.repo_id, str(analysis.id), ctx.effective_branch
            )
        )

    try:
        violations = asyncio.run(_evaluate(content, ctx.action_metadata))
    except Exception as exc:
        logger.exception("OPA evaluation failed for %s: %s", path, exc)
        sm.advance(analysis, sm.ScanMachine, "scan_failed")
        analysis.error_message = str(exc)[:2000]
        analysis.failure_kind = _classify_failure(exc)
        analysis.completed_at = datetime.now(timezone.utc)
        session.add(analysis)
        session.commit()
        if not ctx.is_batch:
            events_pub.publish_event(
                ev.analysis_failed(
                    ctx.org_id, ctx.repo_id, str(analysis.id), str(exc)[:200]
                )
            )
        else:
            tally.batch_any_failed = True
        tally.results.append({"path": path, "status": "failed"})
        return

    # Scoped to this engine, like cloud_scan/terraform_analysis/
    # docker_analysis already do. Unscoped, a workflow violation whose
    # slug is also a Terraform or cloud rule name bound to that other
    # engine's Rule row, taking its severity and weight into the score.
    rule_map: dict[str, Rule] = {
        r.slug: r
        for r in session.exec(
            select(Rule)
            .where(Rule.enabled == True)  # noqa: E712
            .where(Rule.domain == RuleDomain.ci_workflow)
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
            pg_insert(WorkflowFinding)
            .values(
                id=uuid.uuid4(),
                analysis_id=analysis.id,
                workflow_file_id=wf_record.id,
                rule_id=rule.id,
                job=v.job,
                step=v.step,
                step_index=v.step_index,
                fingerprint=fingerprint,
                severity=Severity(v.severity),
                category=Category(v.category),
                line_start=v.line_start,
                line_end=v.line_end,
                message=v.message,
                context=v.context,
                created_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_update(
                constraint="uq_workflow_finding_wf_fingerprint",
                set_={
                    "analysis_id": analysis.id,
                    "severity": Severity(v.severity),
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

    sm.advance(analysis, sm.ScanMachine, "succeeded")
    analysis.score = score
    analysis.grade = grade
    analysis.completed_at = datetime.now(timezone.utc)
    session.add(analysis)
    session.commit()

    tally.changed_wf_ids.add(wf_record.id)

    _resolve_stale_issues(session, wf_record.id, seen_fingerprints)

    if not ctx.is_batch:
        events_pub.publish_event(
            ev.analysis_completed(
                ctx.org_id, ctx.repo_id, str(analysis.id), score, grade, issue_count
            )
        )
    else:
        tally.batch_total_issues += issue_count
        tally.batch_scores.append(score)

    tally.results.append(
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
        "Scan complete: repo=%s path=%s score=%.1f grade=%s issues=%d",
        ctx.repo_id,
        path,
        score,
        grade,
        issue_count,
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

        # Both paths sync the whole branch from GitHub first — refreshing stored
        # content and reconciling deletions — and a single-file run then narrows
        # the analysed set to its own file. Syncing (rather than re-using the
        # stored ``raw_content``) is what keeps a deleted file from being
        # re-analysed off stale content, and doing it *before* the dedup check
        # is what keeps a dedup-skipped file's stored copy from going stale.
        single_path: str | None = None
        if workflow_file_id:
            wf = session.get(WorkflowFile, uuid.UUID(workflow_file_id))
            if wf is None:
                return {"status": "error", "detail": "workflow_file_not_found"}
            # A single-file run analyses the row's own branch, whatever branch
            # the caller passed.
            effective_branch = wf.branch
            single_path = wf.path

        # ``commit_sha`` from a webhook is a *trigger*, not a fetch pin. The
        # sync resolves the branch head itself, so a task delayed behind the
        # lock or a retry can no longer write the commit its event happened to
        # carry over newer content that landed since.
        try:
            sync = sync_workflow_files(
                session,
                repo,
                effective_branch,
                fetch=_fetch_workflow_files,
                resolve_sha=_resolve_ref_sha,
            )
        except WorkflowFetchError as exc:
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
            raise

        # The branch could not be read at all — the ref did not resolve and the
        # listing came back empty, which GitHub reports identically to "this
        # repo has no workflows". Recording a `no_targets` scan here would state
        # as fact the one thing we just established we cannot tell, and it would
        # show in the history as though the repo had been emptied. Say nothing
        # and let the next push, poll or nightly run settle it.
        if sync.ref_unresolved:
            logger.warning(
                "Skipping analysis for %s@%s: branch head could not be resolved",
                repo.full_name,
                effective_branch,
            )
            events_pub.publish_event(ev.analysis_skipped(org_id, repo_id, ""))
            return {"status": "ref_unresolved", "repo_id": repo_id, "results": "[]"}

        # The commit actually analysed, which is what belongs on the scan row.
        # Falls back to the trigger's SHA only when the ref could not be
        # resolved, so the column is populated for manual and scheduled runs.
        analysed_sha = sync.head_sha or commit_sha or None

        analysed_paths: list[str]
        if single_path is not None:
            # Per-file re-analysis: only the target file, using its freshly
            # synced content. If the path is gone it was just reconciled above,
            # so there is nothing to re-analyse and no issues to regenerate.
            if single_path not in sync.contents:
                events_pub.publish_event(ev.analysis_skipped(org_id, repo_id, ""))
                return {
                    "status": "workflow_file_removed",
                    "repo_id": repo_id,
                    "results": "[]",
                }
            analysed_paths = [single_path]
        else:
            analysed_paths = sorted(sync.contents)

        if not analysed_paths:
            now = datetime.now(timezone.utc)
            no_wf_analysis = WorkflowScan(
                repo_id=repo.id,
                workflow_file_id=None,
                content_hash="",
                status=ScanStatus.no_targets,
                triggered_by=ScanTrigger(trigger),
                branch=effective_branch,
                commit_sha=analysed_sha,
                completed_at=now,
            )
            session.add(no_wf_analysis)
            session.commit()
            events_pub.publish_event(
                ev.analysis_no_workflows(org_id, repo_id, str(no_wf_analysis.id))
            )
            return {"status": "no_workflow_files", "repo_id": repo_id, "results": "[]"}

        is_batch = workflow_file_id is None and len(analysed_paths) > 1

        if is_batch:
            events_pub.publish_event(
                ev.analysis_started(org_id, repo_id, "", effective_branch)
            )

        # Hoisted above the loop deliberately — see _collect_action_metadata.
        action_metadata = _collect_action_metadata(
            repo, [sync.contents[p] for p in analysed_paths]
        )

        ctx = _RunContext(
            repo=repo,
            repo_id=repo_id,
            org_id=org_id,
            effective_branch=effective_branch,
            trigger=trigger,
            commit_sha=analysed_sha or "",
            force=force,
            is_batch=is_batch,
            billable=billable,
            action_metadata=action_metadata,
        )
        # The real quota gate. The API pre-check cannot hold on its own — one
        # trigger fans out to one analysis per workflow file, and most analyses
        # arrive here from a push webhook, the polling sweep or installation
        # sync, none of which pass through an API route at all. Counting down a
        # locally-tracked budget (rather than re-querying) keeps the check off
        # the hot path while still stopping the batch at exactly the cap.
        tally = _Tally(
            budget=(
                billing_quota.remaining(session, None, repo.org_id, "analyses")
                if billable
                else None
            )
        )

        for path in analysed_paths:
            if tally.budget is not None and tally.budget <= 0:
                # Out of allowance mid-batch: stop rather than silently
                # over-serving, and remember where so the caller can say which
                # files went unanalysed instead of reporting a clean run.
                tally.quota_stopped_at = path
                break
            # The content the sync read at ``sync.head_sha``, never the row's
            # ``raw_content``: the two agree except when this run's write lost
            # the ordering race, and there the row is the newer one.
            _analyse_one_workflow_file(
                session, ctx, path, sync.contents[path], sync.rows[path], tally
            )

        if is_batch:
            all_failed = tally.batch_any_failed and not any(
                r.get("status") == "completed" for r in tally.results
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
                    sum(tally.batch_scores) / len(tally.batch_scores)
                    if tally.batch_scores
                    else 100.0
                )
                avg_grade = score_to_grade(avg_score)
                events_pub.publish_event(
                    ev.analysis_completed(
                        org_id,
                        repo_id,
                        "",
                        avg_score,
                        avg_grade,
                        tally.batch_total_issues,
                    )
                )

        # Reconcile fixes and refresh the open PR for both single-file and batch
        # runs, but only when a workflow's content actually changed this run.
        # _auto_queue_fix_generation is a no-op when nothing needs regenerating.
        # Fixes are default-branch-only: a feature-branch analysis never queues
        # generation (the query inside is branch-gated too).
        if (
            repo.auto_fix_enabled
            and tally.changed_wf_ids
            and effective_branch == repo.default_branch
        ):
            try:
                _auto_queue_fix_generation(
                    session, repo, org_id, changed_wf_ids=tally.changed_wf_ids
                )
            except Exception:
                logger.exception(
                    "Auto fix generation failed after analysis: repo=%s",
                    repo_id,
                )

        if tally.quota_stopped_at is not None:
            # Say so loudly. A run that quietly analysed four of twelve files
            # and reported "done" is worse than one that failed: the grade it
            # produces looks authoritative while covering a fraction of the
            # repo. The SSE signal is distinct from ``analysis.failed`` because
            # nothing broke and retrying will not help — only upgrading will.
            skipped = len(analysed_paths) - len(tally.results)
            message = (
                f"Scan stopped after {len(tally.results)} of "
                f"{len(analysed_paths)} workflow files: the monthly "
                f"analysis allowance is exhausted. {skipped} file(s) were not "
                f"analysed, starting with {tally.quota_stopped_at}."
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
                "analysed": len(tally.results),
                "skipped": skipped,
                "results": str(tally.results),
            }

        return {
            "status": "done",
            "repo_id": repo_id,
            "results": str(tally.results),
        }


# Retry budget shared by both of ``run_static_analysis``'s retry reasons (lock
# contention and a transient fetch failure), because Celery tracks retries with
# one counter per task rather than one per reason.
MAX_RETRIES = 10


@celery_app.task(name="static_analysis.run", bind=True, max_retries=MAX_RETRIES)
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
    # WorkflowFile.raw_content updates and duplicate WorkflowScan rows.
    with scan_lock(f"static_analysis:{repo_id}") as acquired:
        if not acquired:
            # Another analysis for this repo is already running.  Layers upstream
            # (installation sync dedup) should prevent true duplicates; the retry
            # here covers legitimate concurrent webhook events.  10 × 30 s = 300 s
            # max wait — enough for any realistic analysis to complete.
            raise self.retry(countdown=30, max_retries=MAX_RETRIES)
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
            # ``max_retries`` is passed explicitly and matches the lock branch's
            # budget. Celery keeps a *single* ``request.retries`` counter for the
            # whole task, so without it this fell back to the decorator's 3: on a
            # busy repo that had already burned four lock-contention retries, the
            # first transient GitHub blip exceeded the budget on its very first
            # attempt and failed the analysis outright instead of backing off.
            #
            # The shift is capped so a late retry waits ~16 min, not ~9 h.
            raise self.retry(
                exc=exc,
                countdown=30 * (2 ** min(self.request.retries, 5)),
                max_retries=MAX_RETRIES,
            )


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

    trigger = ScanTrigger.release if force else ScanTrigger.scheduled
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
    """This module's GitHub-listing seam, delegating to ``workflow_sync``.

    Kept as a module-level name rather than calling the service function
    directly because it is the point every analysis test patches to stand in for
    GitHub. Same for ``_resolve_ref_sha`` below.
    """
    return list(fetch_workflow_files_for_repo(repo, ref))


def _resolve_ref_sha(repo: Repository, branch: str) -> str | None:
    """This module's branch-head seam, delegating to ``workflow_sync``."""
    return resolve_branch_head(repo, branch)


async def _evaluate(
    content: str, action_metadata: Mapping[str, Mapping[str, Any]] | None = None
) -> list[OpaViolation]:
    from app.services.opa.evaluator import evaluate_workflow

    return await evaluate_workflow(content, action_metadata=action_metadata)


def _collect_action_metadata(
    repo: Repository, contents: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """What GitHub knows about every action these workflows pin. Never raises.

    Collected once for the whole repository rather than per file: each
    ``_evaluate`` call builds its own event loop and Redis connection, so a
    per-file collector would rebuild both for the same handful of actions. The
    result is a superset for any single workflow, which is harmless —
    ``attach_action_metadata`` filters to the document's own references.

    Any failure yields an empty map, which leaves ``__actions__`` absent and the
    four rules that read it silent. Enrichment must never be the reason a scan
    fails or the reason a finding appears.
    """
    import redis.asyncio as aioredis

    from app.services.github.action_metadata import collect_action_metadata
    from app.services.github.app_client import GitHubAppClient

    async def _collect() -> dict[str, dict[str, Any]]:
        r = aioredis.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call]
        try:
            client = GitHubAppClient(redis_client=r)
            gh = await client.github_for_installation(repo.installation_id)
            return await collect_action_metadata(contents, gh)
        finally:
            await r.aclose()

    try:
        return asyncio.run(_collect())
    except Exception:
        logger.warning(
            "Action metadata collection failed for %s; the rules that need it "
            "will be silent for this scan",
            repo.full_name,
            exc_info=True,
        )
        return {}
