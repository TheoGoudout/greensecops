"""Queuing CI-workflow fix generation.

Shared by the API routes (a user asks for fixes) and the static-analysis worker
(a scan reconciles a repository's fixes with what it found). Both used to carry
their own copy of the "latest unresolved findings" query and of the
create-pending-fixes-then-dispatch sequence.

Every function here that writes stays inside the caller's transaction: nothing
commits. The caller deletes whatever the new fixes replace, creates them,
commits **once**, and only then calls :func:`dispatch_fix_generation` — so a
worker can never pick up a fix that a later failure rolls back, and a failure
half-way never leaves a file with its old fix deleted and no new one queued.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from sqlmodel import Session, col, select, update

from app.models import (
    FixStatus,
    LLMProvider,
    PullRequest,
    PullRequestState,
    Repository,
    ScanStatus,
    UsageEngine,
    UsageMeter,
    WorkflowFile,
    WorkflowFinding,
    WorkflowFix,
    WorkflowScan,
)
from app.services.billing import usage as billing_usage
from app.services.engines import FILE_ENGINES
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.services.llm.catalog import resolve_llm_provider

FindingsByFile = dict[uuid.UUID, list[WorkflowFinding]]


def latest_unresolved_findings(
    session: Session,
    repo: Repository,
    *,
    wf_file_ids: list[uuid.UUID] | None = None,
    finding_ids: list[uuid.UUID] | None = None,
    exclude_manual: bool = False,
) -> FindingsByFile:
    """Open findings from each workflow file's latest completed scan, by file.

    Grouped by workflow file because a fix is one whole-file rewrite (one LLM
    call) per file. Restricted to default-branch files: fixes and PRs only ever
    target the default branch, and feature-branch findings are tracked but
    never fixed.

    ``exclude_manual`` skips findings a prior LLM attempt flagged as
    ``needs_manual_work``, so an implicit bulk selection does not keep
    re-spending generations on findings it already said it cannot fix.
    """
    latest_scan = (
        select(WorkflowScan.id)
        .where(WorkflowScan.workflow_file_id == WorkflowFinding.workflow_file_id)
        .where(WorkflowScan.status == ScanStatus.completed)
        .order_by(
            col(WorkflowScan.completed_at).desc().nulls_last(),
            col(WorkflowScan.created_at).desc(),
        )
        .limit(1)
        .correlate(WorkflowFinding)
        .scalar_subquery()
    )
    query = (
        select(WorkflowFinding)
        .join(WorkflowScan, col(WorkflowFinding.analysis_id) == col(WorkflowScan.id))
        .join(
            WorkflowFile, col(WorkflowFinding.workflow_file_id) == col(WorkflowFile.id)
        )
        .where(WorkflowScan.repo_id == repo.id)
        .where(WorkflowFile.branch == repo.default_branch)
        .where(WorkflowFinding.analysis_id == latest_scan)
        .where(col(WorkflowFinding.resolved_at).is_(None))
        .where(col(WorkflowFinding.ignored_at).is_(None))
    )
    if exclude_manual:
        query = query.where(col(WorkflowFinding.needs_manual_work).is_(False))
    if wf_file_ids is not None:
        query = query.where(col(WorkflowFinding.workflow_file_id).in_(wf_file_ids))
    if finding_ids is not None:
        query = query.where(col(WorkflowFinding.id).in_(finding_ids))

    by_file: FindingsByFile = defaultdict(list)
    for finding in session.exec(query).all():
        # The join on WorkflowFile guarantees workflow_file_id is set.
        assert finding.workflow_file_id is not None
        by_file[finding.workflow_file_id].append(finding)
    return dict(by_file)


def create_pending_fixes(
    session: Session,
    repo: Repository,
    by_file: FindingsByFile,
    *,
    billable: bool,
) -> list[WorkflowFix]:
    """Add a ``pending`` fix per workflow file and link its findings. No commit.

    Files that still carry a fix (e.g. a delivered one kept when ``force`` is
    off) are skipped: the unique constraint allows one fix per file, and the
    worker only processes pending ones.

    ``billable`` charges the org one ``fixes`` unit per generation — the
    billable event is the generation, not the surviving row, so a regenerate
    is charged again. The worker's automatic re-generation after a scan is not
    a user request and passes ``False``.
    """
    if not by_file:
        return []
    taken = set(
        session.exec(
            select(WorkflowFix.workflow_file_id).where(
                col(WorkflowFix.workflow_file_id).in_(list(by_file))
            )
        ).all()
    )
    provider_str, model_str = resolve_llm_provider(repo)

    created: list[WorkflowFix] = []
    for wf_file_id, findings in by_file.items():
        if wf_file_id in taken:
            continue
        fix = WorkflowFix(
            workflow_file_id=wf_file_id,
            llm_provider=LLMProvider(provider_str),
            llm_model=model_str,
            status=FixStatus.pending,
        )
        session.add(fix)
        session.flush()
        for finding in findings:
            finding.fix_id = fix.id
            session.add(finding)
        if billable:
            billing_usage.record_for_org(
                session,
                org_id=repo.org_id,
                repo_id=repo.id,
                meter=UsageMeter.fixes,
                engine=UsageEngine.workflow,
                source_type="fix",
                source_id=fix.id,
                commit=False,
            )
        created.append(fix)

    if billable and created:
        # Incremented in SQL rather than read-modify-written in Python, so two
        # concurrent requests cannot both read N and both write N + 1.
        session.exec(
            update(WorkflowFile)
            .where(col(WorkflowFile.id).in_([f.workflow_file_id for f in created]))
            .values(fix_generation_count=WorkflowFile.fix_generation_count + 1)
        )
    return created


def dispatch_fix_generation(
    repo: Repository, by_file: FindingsByFile, pending_fixes: list[WorkflowFix]
) -> None:
    """Announce the pending fixes and queue one generation task per file.

    Call only after the transaction that created ``pending_fixes`` committed:
    the worker looks the rows up by id. One aggregated ready/failed
    notification is published for the whole run (see ``init_fix_batch``).
    """
    if not pending_fixes:
        return
    # Deferred: services must not import workers at module scope (the worker
    # modules import services). Looked up at call time, which is also the seam
    # the tests patch.
    from app.workers.tasks.fix_generation import init_fix_batch, run_fix_generation

    pending_file_ids = [f.workflow_file_id for f in pending_fixes]
    events_pub.publish_event(
        ev.fix_generating(
            str(repo.org_id),
            str(repo.id),
            fix_ids=[str(f.id) for f in pending_fixes],
            issue_ids=[
                str(finding.id)
                for wf_file_id in pending_file_ids
                for finding in by_file[wf_file_id]
            ],
        )
    )
    batch_id = uuid.uuid4().hex
    init_fix_batch(batch_id, len(pending_file_ids))
    for wf_file_id in pending_file_ids:
        run_fix_generation.delay(
            issue_ids=[str(f.id) for f in by_file[wf_file_id]], batch_id=batch_id
        )


def delete_orphaned_closed_prs(session: Session, repo_id: uuid.UUID) -> None:
    """Delete closed PR records that no fix of any engine references. No commit.

    A closed record on a fix branch makes every later delivery on that branch
    auto-reject its fixes (the closed-PR guard in ``deliver_fixes_batch``), and
    regenerating is an explicit request for a new PR. Records still referenced
    are kept: every engine's fixes share the one ``pull_request`` table, and
    deleting a record a fix still points at would silently clear that fix's
    ``pr_id`` through ``ON DELETE SET NULL``. The next successful delivery
    creates a fresh record — and reuses the GitHub PR itself if the user
    reopened it in the meantime.
    """
    query = (
        select(PullRequest)
        .where(PullRequest.repo_id == repo_id)
        .where(PullRequest.pr_state == PullRequestState.closed)
    )
    fix_models: list[Any] = [WorkflowFix, *(spec.fix_model for spec in FILE_ENGINES)]
    for fix_model in fix_models:
        query = query.where(
            ~col(PullRequest.id).in_(
                select(col(fix_model.pr_id)).where(col(fix_model.pr_id).is_not(None))
            )
        )
    for pr in session.exec(query).all():
        session.delete(pr)
