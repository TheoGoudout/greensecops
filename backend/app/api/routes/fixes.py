import logging
import uuid
from collections import defaultdict

from fastapi import Body, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import col, delete, or_, select

from app.api.deps import (
    CurrentUser,
    GitHubAppClientDep,
    SessionDep,
    authorize_repo,
    get_or_404,
    user_org_ids,
)
from app.api.router import Role, RoleRouter
from app.core.config import settings
from app.core.rate_limit import LIMIT_EXPENSIVE
from app.models import (
    Analysis,
    AnalysisStatus,
    DockerFix,
    Fix,
    FixIssueSummary,
    FixPublic,
    FixStatus,
    Issue,
    LLMProvider,
    PullRequest,
    PullRequestPublic,
    PullRequestState,
    Repository,
    Rule,
    TerraformFix,
    UsageEngine,
    UsageMeter,
    User,
    WorkflowFile,
)
from app.services import state_machines as sm
from app.services.billing import usage as billing_usage
from app.services.billing.quota import enforce_quota
from app.services.delivery_pr import (
    WF_FIX_BRANCH_RE,
    build_delivery_pr_body,
    repo_fix_branch,
    wf_fix_branch,
)
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.services.github.app_client import parse_pr_url
from app.services.state_machines import DELIVERED_FIX_STATUSES, IN_FLIGHT_STATUSES
from app.workers.tasks.fix_delivery import deliver_fixes_batch
from app.workers.tasks.fix_generation import (
    init_fix_batch,
    resolve_llm_provider,
    run_fix_generation,
)

logger = logging.getLogger(__name__)


class BatchFixRequest(BaseModel):
    issue_ids: list[uuid.UUID] | None = None


router = RoleRouter(prefix="/fixes", tags=["fixes"])

# Statuses of fixes a worker is still processing; such fixes cannot be
# regenerated out from under the worker. Sourced from the fix state machine so
# the two never drift.


def _repo_id_for_fix(session: SessionDep, fix: Fix) -> uuid.UUID | None:
    """Resolve the owning repository id for a fix (fix → workflow file)."""
    wf_file = session.get(WorkflowFile, fix.workflow_file_id)
    return wf_file.repo_id if wf_file else None


def _authorize_fix(session: SessionDep, user: User, fix: Fix) -> None:
    """Enforce that ``user`` may act on ``fix`` via its owning repository."""
    if user.is_superuser:
        return
    repo_id = _repo_id_for_fix(session, fix)
    if repo_id is None:
        raise HTTPException(status_code=404, detail="Fix not found")
    authorize_repo(session, user, repo_id, detail="Fix not found")


def _create_pending_fixes(
    session: SessionDep,
    repo: Repository,
    by_wf_file: dict[uuid.UUID, list[Issue]],
) -> list[Fix]:
    """Create a pending Fix per workflow file and link its issues.

    Workflow files that still carry a fix (e.g. a delivered one kept when
    force=False) are skipped — the unique constraint allows only one fix per
    file, and the worker only processes pending fixes.
    """
    taken = set(
        session.exec(
            select(Fix.workflow_file_id).where(
                col(Fix.workflow_file_id).in_(list(by_wf_file))
            )
        ).all()
    )
    provider_str, model_str = resolve_llm_provider(repo)
    wf_files = {
        wf.id: wf
        for wf in session.exec(
            select(WorkflowFile).where(col(WorkflowFile.id).in_(list(by_wf_file)))
        ).all()
    }
    created: list[Fix] = []
    for wf_id, issues in by_wf_file.items():
        if wf_id in taken:
            continue
        fix = Fix(
            workflow_file_id=wf_id,
            llm_provider=LLMProvider(provider_str),
            llm_model=model_str,
            status=FixStatus.pending,
        )
        session.add(fix)
        session.flush()
        for issue in issues:
            issue.fix_id = fix.id
            session.add(issue)
        wf_file = wf_files.get(wf_id)
        if wf_file is not None:
            wf_file.fix_generation_count += 1
            session.add(wf_file)
            # The billable event is the *generation*, not the surviving row —
            # a regenerate discards the old fix and bills again, which is why
            # this counts alongside the lifetime counter rather than being
            # derived from ``SELECT count(*) FROM fix``.
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
    session.commit()
    for fix in created:
        session.refresh(fix)
    return created


def _latest_unresolved_issues(
    session: SessionDep,
    repo_id: uuid.UUID,
    wf_file_ids: list[uuid.UUID] | None = None,
    issue_ids: list[uuid.UUID] | None = None,
    exclude_manual: bool = True,
) -> dict[uuid.UUID, list[Issue]]:
    """Unresolved issues from each workflow file's latest completed analysis.

    Grouped by workflow file → one whole-file fix (one LLM call) per file.
    The latest-analysis correlation guarantees workflow_file_id is set.
    Restricted to default-branch workflow files: fixes and PRs only ever
    target the default branch.

    ``exclude_manual`` skips issues a prior LLM attempt flagged as
    ``needs_manual_work``, so an implicit bulk selection doesn't keep
    re-spending fix generations on issues it already reported it can't fix.
    An explicit retry on a specific workflow/issue set passes ``False`` to
    give the LLM another attempt.
    """
    repo = session.get(Repository, repo_id)
    default_branch = repo.default_branch if repo else "main"
    latest_analysis_subq = (
        select(Analysis.id)
        .where(Analysis.workflow_file_id == Issue.workflow_file_id)
        .where(Analysis.status == AnalysisStatus.completed)
        .order_by(Analysis.completed_at.desc().nulls_last(), Analysis.created_at.desc())  # type: ignore[union-attr]
        .limit(1)
        .correlate(Issue)
        .scalar_subquery()
    )
    query = (
        select(Issue)
        .join(Analysis, Issue.analysis_id == Analysis.id)  # type: ignore[arg-type]
        .join(WorkflowFile, Issue.workflow_file_id == WorkflowFile.id)  # type: ignore[arg-type]
        .where(Analysis.repo_id == repo_id)
        .where(WorkflowFile.branch == default_branch)
        .where(Issue.analysis_id == latest_analysis_subq)
        .where(col(Issue.resolved_at).is_(None))
        .where(col(Issue.ignored_at).is_(None))
    )
    if exclude_manual:
        query = query.where(col(Issue.needs_manual_work).is_(False))
    if wf_file_ids is not None:
        query = query.where(col(Issue.workflow_file_id).in_(wf_file_ids))
    if issue_ids is not None:
        query = query.where(Issue.id.in_(issue_ids))  # type: ignore[attr-defined]

    by_wf_file: dict[uuid.UUID, list[Issue]] = defaultdict(list)
    for issue in session.exec(query).all():
        by_wf_file[issue.workflow_file_id].append(issue)  # type: ignore[index]
    return dict(by_wf_file)


def _queue_fix_generation(
    session: SessionDep,
    repo: Repository,
    by_wf_file: dict[uuid.UUID, list[Issue]],
) -> list[Fix]:
    """Create pending fixes and queue one generation task per workflow file.

    Pending fixes give the UI a DB-backed queued state immediately; the worker
    flips them to generating/ready/failed. Workflow files that still carry a
    fix are skipped by _create_pending_fixes.
    """
    pending_fixes = _create_pending_fixes(session, repo, by_wf_file)
    if not pending_fixes:
        return []
    pending_wf_ids = {f.workflow_file_id for f in pending_fixes}

    events_pub.publish_event(
        ev.fix_generating(
            str(repo.org_id),
            str(repo.id),
            fix_ids=[str(f.id) for f in pending_fixes],
            issue_ids=[
                str(i.id) for wf_id in pending_wf_ids for i in by_wf_file[wf_id]
            ],
        )
    )

    # One aggregated ready/failed notification for the whole run.
    batch_id = uuid.uuid4().hex
    init_fix_batch(batch_id, len(pending_wf_ids))
    for wf_id in pending_wf_ids:
        run_fix_generation.delay(
            issue_ids=[str(i.id) for i in by_wf_file[wf_id]], batch_id=batch_id
        )
    return pending_fixes


def _delete_orphaned_closed_prs(session: SessionDep, repo_id: uuid.UUID) -> None:
    """Delete closed PR records that no fix references anymore.

    A closed record on a fix branch makes every later delivery on that branch
    auto-reject its fixes (the closed-PR guard in deliver_fixes_batch), and
    regenerating is an explicit request for a new PR. Records still referenced
    by surviving fixes are kept — deleting them would silently clear those
    fixes' pr_id (ON DELETE SET NULL). The next successful delivery creates a
    fresh record — and reuses the GitHub PR itself if the user reopened it in
    the meantime.
    """
    # Every engine's fixes share the one `pull_request` table, so a record is
    # orphaned only when *no* engine still points at it. Checking Fix alone used
    # to delete a Terraform or Docker PR record out from under its own fix,
    # clearing that fix's pr_id through the very ON DELETE SET NULL this
    # docstring warns about.
    stale_prs = session.exec(
        select(PullRequest)
        .where(PullRequest.repo_id == repo_id)
        .where(PullRequest.pr_state == PullRequestState.closed)
        .where(
            ~col(PullRequest.id).in_(
                select(col(Fix.pr_id)).where(col(Fix.pr_id).is_not(None))
            )
        )
        .where(
            ~col(PullRequest.id).in_(
                select(col(TerraformFix.pr_id)).where(
                    col(TerraformFix.pr_id).is_not(None)
                )
            )
        )
        .where(
            ~col(PullRequest.id).in_(
                select(col(DockerFix.pr_id)).where(col(DockerFix.pr_id).is_not(None))
            )
        )
    ).all()
    for pr in stale_prs:
        session.delete(pr)


def _fixes_to_public(session: SessionDep, fixes: list[Fix]) -> list[FixPublic]:
    """Bulk-populate FixPublic rows (workflow file, PR, issue summaries)."""
    fix_ids = [f.id for f in fixes]

    wf_ids = list({f.workflow_file_id for f in fixes})
    wf_map: dict[uuid.UUID, WorkflowFile] = {}
    if wf_ids:
        wf_map = {
            w.id: w
            for w in session.exec(
                select(WorkflowFile).where(WorkflowFile.id.in_(wf_ids))  # type: ignore[attr-defined]
            ).all()
        }

    pr_ids = list({f.pr_id for f in fixes if f.pr_id})
    prs_map: dict[uuid.UUID, PullRequest] = {}
    if pr_ids:
        prs_map = {
            pr.id: pr
            for pr in session.exec(
                select(PullRequest).where(PullRequest.id.in_(pr_ids))  # type: ignore[attr-defined]
            ).all()
        }

    issues_by_fix: dict[uuid.UUID, list[Issue]] = defaultdict(list)
    rules_map: dict[uuid.UUID, Rule] = {}
    if fix_ids:
        issues = list(
            session.exec(select(Issue).where(col(Issue.fix_id).in_(fix_ids))).all()
        )
        for issue in issues:
            if issue.fix_id:
                issues_by_fix[issue.fix_id].append(issue)
        rule_ids = list({i.rule_id for i in issues if i.rule_id})
        if rule_ids:
            rules_map = {
                r.id: r
                for r in session.exec(
                    select(Rule).where(Rule.id.in_(rule_ids))  # type: ignore[attr-defined]
                ).all()
            }

    result: list[FixPublic] = []
    for fix in fixes:
        data = FixPublic.model_validate(fix)
        wf_file = wf_map.get(fix.workflow_file_id)
        if wf_file:
            data.workflow_file_path = wf_file.path
            data.repo_id = wf_file.repo_id

        pr = prs_map.get(fix.pr_id) if fix.pr_id else None
        if pr:
            data.pr_url = pr.pr_url
            data.pr_branch = pr.pr_branch
            data.pr_state = pr.pr_state
            data.comment_url = pr.comment_url

        data.issues = [
            FixIssueSummary(
                id=issue.id,
                rule_slug=(
                    rules_map[issue.rule_id].slug
                    if issue.rule_id in rules_map
                    else None
                ),
                severity=issue.severity,
                category=issue.category,
                message=issue.message,
                line_start=issue.line_start,
                line_end=issue.line_end,
            )
            for issue in issues_by_fix.get(fix.id, [])
        ]
        result.append(data)
    return result


@router.get("/", role=Role.user, response_model=list[FixPublic])
def list_fixes(
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID | None = None,
    status: FixStatus | None = None,
    branch: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
) -> list[FixPublic]:
    query = select(Fix)
    if not current_user.is_superuser:
        # Restrict to fixes whose owning repository is in one of the user's orgs.
        allowed_wf_ids = select(WorkflowFile.id).where(
            WorkflowFile.repo_id.in_(  # type: ignore[attr-defined]
                select(Repository.id).where(
                    Repository.org_id.in_(user_org_ids(session, current_user))  # type: ignore[attr-defined]
                )
            )
        )
        query = query.where(Fix.workflow_file_id.in_(allowed_wf_ids))  # type: ignore[attr-defined]
    query = query.join(WorkflowFile, Fix.workflow_file_id == WorkflowFile.id)  # type: ignore[arg-type]
    if repo_id:
        query = query.where(WorkflowFile.repo_id == repo_id)
    if status:
        query = query.where(Fix.status == status)
    if branch:
        query = query.where(
            col(Fix.id).in_(
                select(Issue.fix_id)
                .join(Analysis, col(Issue.analysis_id) == Analysis.id)
                .where(Analysis.branch == branch)
            )
        )
    query = (
        query.order_by(col(WorkflowFile.path).asc(), col(Fix.created_at).desc())
        .offset(skip)
        .limit(limit)
    )
    fixes = list(session.exec(query).all())
    return _fixes_to_public(session, fixes)


@router.get(
    "/pull-requests/{repo_id}",
    role=Role.org_member,
    response_model=list[PullRequestPublic],
)
def list_pull_requests(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[PullRequest]:
    """List a repo's PR rows directly, independent of any Fix's ``pr_id``.

    A ``ready`` fix never carries a ``pr_id`` (see ``_relink_orphaned_fixes``),
    so views that need "does a PR already exist for this branch" must read the
    ``PullRequest`` table itself rather than deriving it from fixes.
    """
    authorize_repo(session, current_user, repo_id)
    return list(
        session.exec(
            select(PullRequest)
            .where(PullRequest.repo_id == repo_id)
            .order_by(col(PullRequest.updated_at).desc().nulls_last())
        ).all()
    )


@router.get("/{fix_id}", role=Role.org_member, response_model=FixPublic)
def get_fix(
    fix_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> FixPublic:
    fix = get_or_404(session, Fix, fix_id)
    _authorize_fix(session, current_user, fix)
    data = _fixes_to_public(session, [fix])[0]

    wf_file = session.get(WorkflowFile, fix.workflow_file_id)
    if wf_file:
        data.base_content = wf_file.raw_content
    return data


@router.post(
    "/generate-for-repo/{repo_id}",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def trigger_fix_generation_for_repo(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    # default_factory, not a literal `BatchFixRequest()`: a bare instance in the
    # signature is evaluated once at import and then shared by every request.
    body: BatchFixRequest = Body(default_factory=BatchFixRequest),
    force: bool = False,
) -> dict[str, int]:
    """Queue one whole-file fix generation per workflow file for issues in a repo.

    When body.issue_ids is provided, only those issues are processed.
    When force=True, delivered fixes are also discarded and regenerated.
    Only issues from the latest analysis per workflow file are targeted.
    """
    repo = authorize_repo(session, current_user, repo_id)

    by_wf_file = _latest_unresolved_issues(
        session,
        repo_id,
        issue_ids=body.issue_ids,
        # An explicit issue selection is a deliberate retry request; only the
        # implicit "generate for everything" path skips manual-flagged issues.
        exclude_manual=body.issue_ids is None,
    )
    if not by_wf_file:
        return {"queued": 0}

    wf_file_ids = list(by_wf_file)

    # Regenerating (force=True) bills as new generations, same as a first-time
    # generate — usage is a cumulative count of generation events, not a live
    # row count, so a discard-and-recreate here still adds to the total.
    enforce_quota(
        session,
        current_user,
        repo.org_id,
        "fixes",
        requested=len(by_wf_file),
    )

    delete_stmt = delete(Fix).where(col(Fix.workflow_file_id).in_(wf_file_ids))
    if not force:
        delete_stmt = delete_stmt.where(col(Fix.status) != FixStatus.delivered)
    session.exec(delete_stmt)
    session.commit()

    repo = get_or_404(session, Repository, repo_id, detail="Repository not found")
    if not repo.is_accessible:
        raise HTTPException(status_code=403, detail="Repository is not accessible")

    pending_fixes = _queue_fix_generation(session, repo, by_wf_file)
    return {"queued": len(pending_fixes)}


class WorkflowDeliverRequest(BaseModel):
    fix_id: uuid.UUID


@router.post(
    "/deliver-for-workflow", role=Role.user, limit=LIMIT_EXPENSIVE, status_code=202
)
def trigger_workflow_delivery(
    body: WorkflowDeliverRequest,
    session: SessionDep,
    current_user: CurrentUser,
    force: bool = False,
) -> dict[str, str]:
    """Deliver one workflow file's fix as a single PR.

    When force=True, a fix in any status is accepted (not just ready).
    """
    fix = session.get(Fix, body.fix_id)
    if not fix or (not force and fix.status != FixStatus.ready):
        raise HTTPException(status_code=404, detail="No ready fix found")

    wf_file = session.get(WorkflowFile, fix.workflow_file_id)
    repo = session.get(Repository, wf_file.repo_id) if wf_file else None
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    if not current_user.is_superuser:
        authorize_repo(session, current_user, repo.id, detail="Repository not found")
    if not repo.is_accessible:
        raise HTTPException(status_code=403, detail="Repository is not accessible")

    # Stable branch: reuse the branch of the fix's own PR when it has one.
    existing_pr = session.get(PullRequest, fix.pr_id) if fix.pr_id else None
    pr_branch = (
        existing_pr.pr_branch if existing_pr else wf_fix_branch(fix.workflow_file_id)
    )

    pr_body = build_delivery_pr_body(session, repo.id, [fix], existing_pr)
    deliver_fixes_batch.delay(
        fix_ids=[str(fix.id)],
        repo_id=str(repo.id),
        pr_branch=pr_branch,
        pr_title=f"fix(ci): apply {settings.PROJECT_NAME} fixes for workflow",
        pr_body=pr_body,
        force=force,
    )
    return {"status": "queued"}


@router.post(
    "/deliver-for-repo/{repo_id}",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def trigger_repo_delivery(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    force: bool = False,
) -> dict[str, str]:
    """Deliver all ready fixes for a repo as a single multi-file PR.

    When force=True, fixes in any status are included (not just ready).
    """
    repo = authorize_repo(session, current_user, repo_id)
    if not repo.is_accessible:
        raise HTTPException(status_code=403, detail="Repository is not accessible")

    base_query = (
        select(Fix)
        .join(WorkflowFile, Fix.workflow_file_id == WorkflowFile.id)  # type: ignore[arg-type]
        .where(WorkflowFile.repo_id == repo_id)
    )
    query = base_query if force else base_query.where(Fix.status == FixStatus.ready)
    fixes = list(session.exec(query).all())
    if not fixes:
        raise HTTPException(status_code=404, detail="No ready fixes found")

    existing_pr = session.exec(
        select(PullRequest)
        .join(Fix, Fix.pr_id == PullRequest.id)  # type: ignore[arg-type]
        .join(WorkflowFile, Fix.workflow_file_id == WorkflowFile.id)  # type: ignore[arg-type]
        .where(WorkflowFile.repo_id == repo_id)
        .order_by(PullRequest.updated_at.desc().nulls_last())  # type: ignore[union-attr]
        .limit(1)
    ).first()
    pr_branch = existing_pr.pr_branch if existing_pr else repo_fix_branch(repo_id)

    pr_body = build_delivery_pr_body(session, repo_id, fixes, existing_pr)
    deliver_fixes_batch.delay(
        fix_ids=[str(f.id) for f in fixes],
        repo_id=str(repo_id),
        pr_branch=pr_branch,
        pr_title=f"fix(ci): apply all {settings.PROJECT_NAME} fixes",
        pr_body=pr_body,
        force=force,
    )
    return {"status": "queued"}


@router.delete("/{fix_id}", role=Role.org_admin, status_code=204)
def reject_fix(
    fix_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> None:
    fix = get_or_404(session, Fix, fix_id)
    _authorize_fix(session, current_user, fix)
    # try_advance: rejecting an already terminal fix (already rejected_by_user,
    # or failed) is an idempotent no-op rather than an error, so the DELETE stays
    # safe to retry.
    if not sm.try_advance(fix, sm.FixMachine, "reject"):
        return
    session.add(fix)
    session.commit()

    wf_file = session.get(WorkflowFile, fix.workflow_file_id)
    repo = session.get(Repository, wf_file.repo_id) if wf_file else None
    if repo:
        events_pub.publish_event(
            ev.fix_rejected(str(repo.org_id), str(repo.id), str(fix_id))
        )


@router.post(
    "/regenerate-for-repo/{repo_id}",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def regenerate_fixes_for_repo(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, int]:
    """Discard a repo's regenerable fixes and re-trigger generation.

    A fix is regenerable when no worker is processing it and its PR, if any,
    was not merged — merged code changes were already applied. Fixes whose
    workflow file has no unresolved issues left in its latest analysis are
    kept: there is nothing to regenerate them from.
    """
    repo = authorize_repo(session, current_user, repo_id)
    if not repo.is_accessible:
        raise HTTPException(status_code=403, detail="Repository is not accessible")

    # pr_state is nullable, and NULL != 'merged' is NULL in SQL — the IS NULL
    # arms keep fixes on stateless PR records eligible.
    eligible = list(
        session.exec(
            select(Fix)
            .join(WorkflowFile, Fix.workflow_file_id == WorkflowFile.id)  # type: ignore[arg-type]
            .join(PullRequest, Fix.pr_id == PullRequest.id, isouter=True)  # type: ignore[arg-type]
            .where(WorkflowFile.repo_id == repo_id)
            .where(col(Fix.status).not_in(IN_FLIGHT_STATUSES))
            .where(
                or_(
                    col(Fix.pr_id).is_(None),
                    col(PullRequest.pr_state).is_(None),
                    PullRequest.pr_state != PullRequestState.merged,
                )
            )
        ).all()
    )
    if not eligible:
        return {"queued": 0}

    by_wf_file = _latest_unresolved_issues(
        session, repo_id, wf_file_ids=[f.workflow_file_id for f in eligible]
    )
    fixes_to_delete = [f for f in eligible if f.workflow_file_id in by_wf_file]
    if not fixes_to_delete:
        return {"queued": 0}

    enforce_quota(
        session,
        current_user,
        repo.org_id,
        "fixes",
        requested=len(by_wf_file),
    )

    session.exec(delete(Fix).where(col(Fix.id).in_([f.id for f in fixes_to_delete])))
    _delete_orphaned_closed_prs(session, repo_id)
    session.commit()

    pending_fixes = _queue_fix_generation(session, repo, by_wf_file)
    return {"queued": len(pending_fixes)}


@router.post(
    "/regenerate-for-workflow/{fix_id}",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def regenerate_fixes_for_workflow(
    fix_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, int]:
    """Discard one workflow file's fix and re-trigger generation.

    Rejected while a worker is processing the fix, once its PR was merged
    (the code changes were already applied), and when the latest analysis
    has no unresolved issues left to regenerate from.
    """
    fix = get_or_404(session, Fix, fix_id)
    _authorize_fix(session, current_user, fix)

    if fix.status in IN_FLIGHT_STATUSES:
        raise HTTPException(
            status_code=409, detail=f"Fix is currently {fix.status.value}"
        )
    pr = session.get(PullRequest, fix.pr_id) if fix.pr_id else None
    if pr and pr.pr_state == PullRequestState.merged:
        raise HTTPException(
            status_code=409, detail="Fix was already merged; nothing to regenerate"
        )

    wf_file = session.get(WorkflowFile, fix.workflow_file_id)
    repo = session.get(Repository, wf_file.repo_id) if wf_file else None
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    if not repo.is_accessible:
        raise HTTPException(status_code=403, detail="Repository is not accessible")

    by_wf_file = _latest_unresolved_issues(
        session,
        repo.id,
        wf_file_ids=[fix.workflow_file_id],
        # Explicit retry of this one workflow's fix — give the LLM another
        # attempt even if a prior run flagged it as needing manual work.
        exclude_manual=False,
    )
    if not by_wf_file:
        raise HTTPException(
            status_code=409,
            detail="No unresolved issues found for this workflow file",
        )

    enforce_quota(session, current_user, repo.org_id, "fixes", requested=1)

    session.delete(fix)
    _delete_orphaned_closed_prs(session, repo.id)
    session.commit()

    pending_fixes = _queue_fix_generation(session, repo, by_wf_file)
    return {"queued": len(pending_fixes)}


@router.post(
    "/{fix_id}/regenerate", role=Role.org_admin, limit=LIMIT_EXPENSIVE, status_code=202
)
def regenerate_failed_fix(
    fix_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, str]:
    """Retry a failed fix in place (``failed`` -> ``pending``), reusing the row.

    Unlike ``regenerate-for-workflow`` (which discards the row and creates a new
    one), this recovers a fix that failed generation/precheck without losing its
    identity or PR linkage. Only legal from ``failed``.
    """
    fix = get_or_404(session, Fix, fix_id)
    _authorize_fix(session, current_user, fix)

    wf_file = session.get(WorkflowFile, fix.workflow_file_id)
    repo = session.get(Repository, wf_file.repo_id) if wf_file else None
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    if not repo.is_accessible:
        raise HTTPException(status_code=403, detail="Repository is not accessible")

    # Issues still needing this fix (a resolved/ignored issue no longer counts).
    issue_ids = [
        str(i.id)
        for i in session.exec(
            select(Issue)
            .where(Issue.fix_id == fix.id)
            .where(col(Issue.resolved_at).is_(None))
            .where(col(Issue.ignored_at).is_(None))
        ).all()
    ]
    if not issue_ids:
        raise HTTPException(
            status_code=409, detail="No unresolved issues left for this fix"
        )

    try:
        sm.advance(fix, sm.FixMachine, "regenerate")
    except sm.IllegalTransition:
        raise HTTPException(
            status_code=409,
            detail=f"Fix is {fix.status.value}; only a failed fix can be regenerated",
        )
    fix.error_message = None
    session.add(fix)
    session.commit()

    events_pub.publish_event(
        ev.fix_pending(str(repo.org_id), str(repo.id), str(fix.id))
    )
    run_fix_generation.delay(issue_ids=issue_ids)
    return {"status": "queued", "fix_id": str(fix_id)}


def _relink_orphaned_fixes(session: SessionDep, repo: Repository) -> int:
    """Reconnect fixes whose ``pr_id`` was lost to the repo's existing PR rows.

    A ``PullRequest`` row deleted while fixes still referenced it clears their
    ``pr_id`` (ON DELETE SET NULL), orphaning fixes that a matching PR record may
    still cover. Matching is by the deterministic greensecops branch name — the
    same key delivery uses — never a fuzzy heuristic, and only NULL links are
    filled (an existing link is never overwritten). Returns the number relinked.
    """
    orphans = list(
        session.exec(
            select(Fix)
            .join(WorkflowFile, Fix.workflow_file_id == WorkflowFile.id)  # type: ignore[arg-type]
            .where(WorkflowFile.repo_id == repo.id)
            .where(col(Fix.pr_id).is_(None))
        ).all()
    )
    if not orphans:
        return 0

    # prefix8 -> fix, dropping any prefix shared by >1 fix (ambiguous, so skip it).
    fix_by_prefix: dict[str, Fix | None] = {}
    for fix in orphans:
        prefix = str(fix.workflow_file_id)[:8]
        fix_by_prefix[prefix] = None if prefix in fix_by_prefix else fix

    prs = list(
        session.exec(select(PullRequest).where(PullRequest.repo_id == repo.id)).all()
    )
    batch_branch = repo_fix_branch(repo.id)
    batch_prs = [pr for pr in prs if pr.pr_branch == batch_branch]

    relinked = 0
    for pr in prs:
        match = WF_FIX_BRANCH_RE.fullmatch(pr.pr_branch)
        if not match:
            continue
        candidate = fix_by_prefix.get(match.group(1))
        if candidate is not None and candidate.pr_id is None:
            candidate.pr_id = pr.id
            session.add(candidate)
            relinked += 1

    # Repo-wide batch PR: bundle-level match, only when unambiguous (exactly one
    # such record) and only for fixes that were actually delivered.
    if len(batch_prs) == 1:
        batch_pr = batch_prs[0]
        for fix in orphans:
            if fix.pr_id is None and fix.status in DELIVERED_FIX_STATUSES:
                fix.pr_id = batch_pr.id
                session.add(fix)
                relinked += 1

    return relinked


@router.post("/sync-pr-status/{repo_id}", role=Role.org_member, limit=LIMIT_EXPENSIVE)
async def sync_pr_statuses(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    github_client: GitHubAppClientDep,
) -> dict[str, int]:
    repo = authorize_repo(session, current_user, repo_id)

    relinked = _relink_orphaned_fixes(session, repo)
    if relinked:
        session.commit()

    open_prs = list(
        session.exec(
            select(PullRequest)
            .where(PullRequest.repo_id == repo_id)
            .where(PullRequest.pr_url.is_not(None))  # type: ignore[union-attr]
            .where(PullRequest.pr_state == PullRequestState.open)
        ).all()
    )
    if not open_prs:
        return {"synced": 0, "updated": 0, "relinked": relinked}

    updated = 0
    for pr_record in open_prs:
        pr_url = pr_record.pr_url
        parsed = parse_pr_url(pr_url)  # type: ignore[arg-type]
        if not parsed or not repo.installation_id:
            continue
        full_name, pr_number = parsed
        try:
            new_state = await github_client.get_pr_state(
                repo.installation_id, full_name, pr_number
            )
        except Exception:
            logger.warning("Failed to fetch PR state for %s", pr_url, exc_info=True)
            continue

        if new_state == PullRequestState.open:
            continue

        pr_event = "merge" if new_state == PullRequestState.merged else "close"
        if not sm.try_advance(pr_record, sm.PullRequestMachine, pr_event):
            continue
        session.add(pr_record)
        updated += 1

        pr_fixes = list(
            session.exec(select(Fix).where(Fix.pr_id == pr_record.id)).all()
        )
        events_pub.publish_event(
            ev.pr_closed(
                str(repo.org_id),
                str(repo.id),
                str(pr_fixes[0].id) if pr_fixes else str(pr_record.id),
                pr_url,  # type: ignore[arg-type]
                new_state == "merged",
            )
        )

    if updated:
        session.commit()

    return {"synced": len(open_prs), "updated": updated, "relinked": relinked}
