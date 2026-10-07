import logging
import uuid
from collections import defaultdict
from typing import Any

from fastapi import Body, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_
from sqlmodel import col, delete, or_, select

from app.api.deps import (
    CurrentUser,
    GitHubAppClientDep,
    SessionDep,
    authorize_repo,
    get_or_404,
    user_org_ids,
)
from app.api.engine_routes import (
    repository_activity,
    require_idle,
    workflow_file_activity,
)
from app.api.mappers import to_public
from app.api.router import Role, RoleRouter
from app.core.config import settings
from app.core.rate_limit import LIMIT_EXPENSIVE
from app.models import (
    FixFindingSummary,
    FixStatus,
    PullRequest,
    PullRequestPublic,
    PullRequestState,
    Repository,
    Rule,
    TargetAction,
    WorkflowFile,
    WorkflowFinding,
    WorkflowFix,
    WorkflowFixPublic,
    WorkflowScan,
)
from app.services import state_machines as sm
from app.services import workflow_fixes
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
from app.workers.tasks.fix_generation import run_fix_generation

logger = logging.getLogger(__name__)


class BatchFixRequest(BaseModel):
    issue_ids: list[uuid.UUID] | None = None


router = RoleRouter()


def require_accessible(repo: Repository) -> None:
    """403 when the GitHub App can no longer reach ``repo``."""
    if not repo.is_accessible:
        raise HTTPException(status_code=403, detail="Repository is not accessible")


def _fix_with_owners(
    session: SessionDep, fix_id: uuid.UUID
) -> tuple[WorkflowFix, WorkflowFile, Repository]:
    """A fix with the workflow file and repository that own it.

    Authorization is the router's: every route calling this declares an org
    role, which ``ORG_RESOLVERS["fix_id"]`` resolves through these same rows.
    Both foreign keys are non-null and cascading, so once the fix exists its
    owners do too.
    """
    fix = get_or_404(session, WorkflowFix, fix_id)
    wf_file = session.get_one(WorkflowFile, fix.workflow_file_id)
    return fix, wf_file, session.get_one(Repository, wf_file.repo_id)


def _replace_fixes(
    session: SessionDep,
    repo: Repository,
    by_file: workflow_fixes.FindingsByFile,
    *,
    delete_where: Any,
    drop_closed_prs: bool = False,
) -> int:
    """Swap the matching fixes for fresh pending ones, then queue generation.

    One transaction: the old fixes are deleted and the new ones created and
    billed together, so a failure part-way leaves the previous fixes in place
    rather than a file with nothing. Tasks are dispatched only after the commit,
    so a worker never looks for a row that does not exist yet.
    """
    session.exec(delete(WorkflowFix).where(delete_where))
    if drop_closed_prs:
        workflow_fixes.delete_orphaned_closed_prs(session, repo.id)
    session.flush()
    pending = workflow_fixes.create_pending_fixes(session, repo, by_file, billable=True)
    session.commit()
    workflow_fixes.dispatch_fix_generation(repo, by_file, pending)
    return len(pending)


def _fixes_to_public(
    session: SessionDep, fixes: list[WorkflowFix]
) -> list[WorkflowFixPublic]:
    """Bulk-populate WorkflowFixPublic rows (workflow file, PR, finding summaries)."""
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

    issues_by_fix: dict[uuid.UUID, list[WorkflowFinding]] = defaultdict(list)
    rules_map: dict[uuid.UUID, Rule] = {}
    if fix_ids:
        issues = list(
            session.exec(
                select(WorkflowFinding).where(col(WorkflowFinding.fix_id).in_(fix_ids))
            ).all()
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

    result: list[WorkflowFixPublic] = []
    for fix in fixes:
        wf_file = wf_map.get(fix.workflow_file_id)
        pr = prs_map.get(fix.pr_id) if fix.pr_id else None
        # ``file_path`` lives on the joined WorkflowFile rather than on the fix
        # row the way Docker's and Terraform's do, so it is an override here
        # rather than a plain attribute copy.
        result.append(
            to_public(
                fix,
                WorkflowFixPublic,
                file_path=wf_file.path if wf_file else "",
                repo_id=wf_file.repo_id if wf_file else None,
                pr_url=pr.pr_url if pr else None,
                pr_branch=pr.pr_branch if pr else None,
                pr_state=pr.pr_state if pr else None,
                comment_url=pr.comment_url if pr else None,
                findings=[
                    FixFindingSummary(
                        id=finding.id,
                        rule_slug=(
                            rules_map[finding.rule_id].slug
                            if finding.rule_id in rules_map
                            else None
                        ),
                        severity=finding.severity,
                        category=finding.category,
                        message=finding.message,
                        line_start=finding.line_start,
                        line_end=finding.line_end,
                    )
                    for finding in issues_by_fix.get(fix.id, [])
                ],
            )
        )
    return result


@router.get("/fixes", role=Role.user, response_model=list[WorkflowFixPublic])
def list_fixes(
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID | None = None,
    status: FixStatus | None = None,
    branch: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
) -> list[WorkflowFixPublic]:
    query = select(WorkflowFix)
    if not current_user.is_superuser:
        # Restrict to fixes whose owning repository is in one of the user's orgs.
        allowed_wf_ids = select(WorkflowFile.id).where(
            WorkflowFile.repo_id.in_(  # type: ignore[attr-defined]
                select(Repository.id).where(
                    Repository.org_id.in_(user_org_ids(session, current_user))  # type: ignore[attr-defined]
                )
            )
        )
        query = query.where(WorkflowFix.workflow_file_id.in_(allowed_wf_ids))  # type: ignore[attr-defined]
    query = query.join(WorkflowFile, WorkflowFix.workflow_file_id == WorkflowFile.id)  # type: ignore[arg-type]
    if repo_id:
        query = query.where(WorkflowFile.repo_id == repo_id)
    if status:
        query = query.where(WorkflowFix.status == status)
    if branch:
        query = query.where(
            col(WorkflowFix.id).in_(
                select(WorkflowFinding.fix_id)
                .join(WorkflowScan, col(WorkflowFinding.analysis_id) == WorkflowScan.id)
                .where(WorkflowScan.branch == branch)
            )
        )
    query = (
        query.order_by(col(WorkflowFile.path).asc(), col(WorkflowFix.created_at).desc())
        .offset(skip)
        .limit(limit)
    )
    fixes = list(session.exec(query).all())
    return _fixes_to_public(session, fixes)


@router.get(
    "/repositories/{repo_id}/pull-requests",
    role=Role.org_member,
    response_model=list[PullRequestPublic],
)
def list_pull_requests(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[PullRequest]:
    """List a repo's PR rows directly, independent of any fix's ``pr_id``.

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


@router.get("/fixes/{fix_id}", role=Role.org_member, response_model=WorkflowFixPublic)
def get_fix(
    fix_id: uuid.UUID,
    session: SessionDep,
) -> WorkflowFixPublic:
    fix, wf_file, _repo = _fix_with_owners(session, fix_id)
    data = _fixes_to_public(session, [fix])[0]
    # The content the rewrite was generated from, so the diff on screen is the
    # diff delivery will push. Falls back to the stored snapshot for fixes
    # generated before base_content was recorded.
    data.base_content = fix.base_content or wf_file.raw_content
    return data


@router.post(
    "/repositories/{repo_id}/fixes",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def generate_repository_fixes(
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
    require_idle(
        repository_activity(session, repo_id), TargetAction.generate, "repository"
    )

    by_file = workflow_fixes.latest_unresolved_findings(
        session,
        repo,
        finding_ids=body.issue_ids,
        # An explicit issue selection is a deliberate retry request; only the
        # implicit "generate for everything" path skips manual-flagged issues.
        exclude_manual=body.issue_ids is None,
    )
    if not by_file:
        return {"queued": 0}

    # Regenerating (force=True) bills as new generations, same as a first-time
    # generate — usage is a cumulative count of generation events, not a live
    # row count, so a discard-and-recreate here still adds to the total.
    enforce_quota(session, current_user, repo.org_id, "fixes", requested=len(by_file))
    require_accessible(repo)

    replaced: Any = col(WorkflowFix.workflow_file_id).in_(list(by_file))
    if not force:
        replaced = and_(replaced, col(WorkflowFix.status) != FixStatus.delivered)
    return {"queued": _replace_fixes(session, repo, by_file, delete_where=replaced)}


@router.post(
    "/fixes/{fix_id}/deliveries",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def deliver_fix(
    fix_id: uuid.UUID,
    session: SessionDep,
    force: bool = False,
) -> dict[str, str]:
    """Deliver one workflow file's fix as a single PR.

    When force=True, a fix in any status is accepted (not just ready).
    """
    fix, wf_file, repo = _fix_with_owners(session, fix_id)
    if not force and fix.status != FixStatus.ready:
        raise HTTPException(status_code=404, detail="No ready fix found")
    require_accessible(repo)
    # ``force`` overrides the *fix status* precondition above, not this one: a
    # running scan or an in-flight sibling is a collision, not a stale state the
    # caller is knowingly overriding.
    require_idle(
        workflow_file_activity(session, wf_file), TargetAction.deliver, "workflow file"
    )

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
    "/repositories/{repo_id}/deliveries",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def deliver_repository_fixes(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    force: bool = False,
) -> dict[str, str]:
    """Deliver all ready fixes for a repo as a single multi-file PR.

    When force=True, fixes in any status are included (not just ready).
    """
    repo = authorize_repo(session, current_user, repo_id)
    require_accessible(repo)
    require_idle(
        repository_activity(session, repo_id), TargetAction.deliver, "repository"
    )

    query = (
        select(WorkflowFix)
        .join(WorkflowFile, col(WorkflowFix.workflow_file_id) == col(WorkflowFile.id))
        .where(WorkflowFile.repo_id == repo_id)
    )
    if not force:
        query = query.where(WorkflowFix.status == FixStatus.ready)
    fixes = list(session.exec(query).all())
    if not fixes:
        raise HTTPException(status_code=404, detail="No ready fixes found")

    existing_pr = session.exec(
        select(PullRequest)
        .join(WorkflowFix, col(WorkflowFix.pr_id) == col(PullRequest.id))
        .join(WorkflowFile, col(WorkflowFix.workflow_file_id) == col(WorkflowFile.id))
        .where(WorkflowFile.repo_id == repo_id)
        .order_by(col(PullRequest.updated_at).desc().nulls_last())
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


@router.delete("/fixes/{fix_id}", role=Role.org_admin, status_code=204)
def reject_fix(
    fix_id: uuid.UUID,
    session: SessionDep,
) -> None:
    fix, _wf_file, repo = _fix_with_owners(session, fix_id)
    # try_advance: rejecting an already terminal fix (already rejected_by_user,
    # or failed) is an idempotent no-op rather than an error, so the DELETE stays
    # safe to retry.
    if not sm.try_advance(fix, sm.FixMachine, "reject"):
        return
    session.add(fix)
    session.commit()
    events_pub.publish_event(
        ev.fix_rejected(str(repo.org_id), str(repo.id), str(fix_id))
    )


@router.post(
    "/repositories/{repo_id}/fixes/regenerate",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def regenerate_repository_fixes(
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
    require_accessible(repo)
    require_idle(
        repository_activity(session, repo_id), TargetAction.generate, "repository"
    )

    # pr_state is nullable, and NULL != 'merged' is NULL in SQL — the IS NULL
    # arms keep fixes on stateless PR records eligible.
    eligible = list(
        session.exec(
            select(WorkflowFix)
            .join(
                WorkflowFile, col(WorkflowFix.workflow_file_id) == col(WorkflowFile.id)
            )
            .join(
                PullRequest, col(WorkflowFix.pr_id) == col(PullRequest.id), isouter=True
            )
            .where(WorkflowFile.repo_id == repo_id)
            .where(col(WorkflowFix.status).not_in(IN_FLIGHT_STATUSES))
            .where(
                or_(
                    col(WorkflowFix.pr_id).is_(None),
                    col(PullRequest.pr_state).is_(None),
                    PullRequest.pr_state != PullRequestState.merged,
                )
            )
        ).all()
    )
    if not eligible:
        return {"queued": 0}

    by_file = workflow_fixes.latest_unresolved_findings(
        session, repo, wf_file_ids=[f.workflow_file_id for f in eligible]
    )
    to_replace = [f.id for f in eligible if f.workflow_file_id in by_file]
    if not to_replace:
        return {"queued": 0}

    enforce_quota(session, current_user, repo.org_id, "fixes", requested=len(by_file))
    queued = _replace_fixes(
        session,
        repo,
        by_file,
        delete_where=col(WorkflowFix.id).in_(to_replace),
        drop_closed_prs=True,
    )
    return {"queued": queued}


@router.post(
    "/fixes/{fix_id}/regenerate",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def regenerate_fix(
    fix_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, int]:
    """Discard one workflow file's fix and re-trigger generation.

    Rejected while a worker is processing the fix, once its PR was merged
    (the code changes were already applied), and when the latest analysis
    has no unresolved issues left to regenerate from.
    """
    fix, wf_file, repo = _fix_with_owners(session, fix_id)

    if fix.status in IN_FLIGHT_STATUSES:
        raise HTTPException(
            status_code=409, detail=f"Workflow fix is currently {fix.status.value}"
        )
    pr = session.get(PullRequest, fix.pr_id) if fix.pr_id else None
    if pr and pr.pr_state == PullRequestState.merged:
        raise HTTPException(
            status_code=409,
            detail="Workflow fix was already merged; nothing to regenerate",
        )
    require_accessible(repo)
    # The in-flight check above covers this fix; this one covers the scan that
    # is about to replace the issues it would be regenerated from.
    require_idle(
        workflow_file_activity(session, wf_file),
        TargetAction.generate,
        "workflow file",
    )

    by_file = workflow_fixes.latest_unresolved_findings(
        session,
        repo,
        wf_file_ids=[fix.workflow_file_id],
        # Explicit retry of this one workflow's fix — give the LLM another
        # attempt even if a prior run flagged it as needing manual work.
        exclude_manual=False,
    )
    if not by_file:
        raise HTTPException(
            status_code=409,
            detail="No unresolved issues found for this workflow file",
        )

    enforce_quota(session, current_user, repo.org_id, "fixes", requested=1)
    queued = _replace_fixes(
        session,
        repo,
        by_file,
        delete_where=col(WorkflowFix.id) == fix.id,
        drop_closed_prs=True,
    )
    return {"queued": queued}


@router.post(
    "/fixes/{fix_id}/retry", role=Role.org_admin, limit=LIMIT_EXPENSIVE, status_code=202
)
def retry_fix(
    fix_id: uuid.UUID,
    session: SessionDep,
) -> dict[str, str]:
    """Retry a failed fix in place (``failed`` -> ``pending``), reusing the row.

    Unlike ``regenerate-for-workflow`` (which discards the row and creates a new
    one), this recovers a fix that failed generation/precheck without losing its
    identity or PR linkage. Only legal from ``failed``.
    """
    fix, wf_file, repo = _fix_with_owners(session, fix_id)
    require_accessible(repo)
    require_idle(
        workflow_file_activity(session, wf_file),
        TargetAction.generate,
        "workflow file",
    )

    # Issues still needing this fix (a resolved/ignored issue no longer counts).
    issue_ids = [
        str(issue_id)
        for issue_id in session.exec(
            select(WorkflowFinding.id)
            .where(WorkflowFinding.fix_id == fix.id)
            .where(col(WorkflowFinding.resolved_at).is_(None))
            .where(col(WorkflowFinding.ignored_at).is_(None))
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
            detail=f"Workflow fix is {fix.status.value}; only a failed fix can be regenerated",
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
            select(WorkflowFix)
            .join(WorkflowFile, WorkflowFix.workflow_file_id == WorkflowFile.id)  # type: ignore[arg-type]
            .where(WorkflowFile.repo_id == repo.id)
            .where(col(WorkflowFix.pr_id).is_(None))
        ).all()
    )
    if not orphans:
        return 0

    # prefix8 -> fix, dropping any prefix shared by >1 fix (ambiguous, so skip it).
    fix_by_prefix: dict[str, WorkflowFix | None] = {}
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


@router.post(
    "/repositories/{repo_id}/pull-requests/sync",
    role=Role.org_member,
    limit=LIMIT_EXPENSIVE,
)
async def sync_pull_request_statuses(
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
            session.exec(
                select(WorkflowFix).where(WorkflowFix.pr_id == pr_record.id)
            ).all()
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
