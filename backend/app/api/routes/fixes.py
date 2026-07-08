import logging
import uuid
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import col, delete, select

from app.api.deps import (
    CurrentUser,
    GitHubAppClientDep,
    SessionDep,
    authorize_repo,
    get_or_404,
    user_org_ids,
)
from app.core.config import settings
from app.models import (
    Analysis,
    AnalysisStatus,
    Fix,
    FixIssueSummary,
    FixPublic,
    FixStatus,
    Issue,
    PullRequest,
    PullRequestState,
    Repository,
    Rule,
    User,
    WorkflowFile,
)
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.services.github.app_client import parse_pr_url
from app.services.pr_body import IssueInfo, build_pr_body
from app.workers.tasks.fix_delivery import deliver_fixes_batch
from app.workers.tasks.fix_generation import run_fix_generation

logger = logging.getLogger(__name__)


class BatchFixRequest(BaseModel):
    issue_ids: list[uuid.UUID] | None = None


router = APIRouter(prefix="/fixes", tags=["fixes"])


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


def _issues_info_for_fixes(fixes: list[Fix]) -> list[IssueInfo]:
    """Build PR-body issue summaries from the issues each fix addresses."""
    return [
        IssueInfo(
            rule_slug=issue.rule.slug if issue.rule else "fix",
            rule_title=issue.rule.title if issue.rule else "Fix",
            category=issue.category.value if issue.category else "unknown",
            severity=issue.severity.value if issue.severity else "unknown",
            message=issue.message or "",
        )
        for fix in fixes
        for issue in fix.issues
    ]


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


@router.get("/", response_model=list[FixPublic])
def list_fixes(
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID | None = None,
    status: FixStatus | None = None,
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
    if repo_id:
        query = query.join(
            WorkflowFile,
            Fix.workflow_file_id == WorkflowFile.id,  # type: ignore[arg-type]
        ).where(WorkflowFile.repo_id == repo_id)
    if status:
        query = query.where(Fix.status == status)
    query = query.order_by(col(Fix.created_at).desc()).offset(skip).limit(limit)
    fixes = list(session.exec(query).all())
    return _fixes_to_public(session, fixes)


@router.get("/{fix_id}", response_model=FixPublic)
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


@router.post("/generate-for-repo/{repo_id}", status_code=202)
def trigger_fix_generation_for_repo(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    body: BatchFixRequest = BatchFixRequest(),
    force: bool = False,
) -> dict[str, int]:
    """Queue one whole-file fix generation per workflow file for issues in a repo.

    When body.issue_ids is provided, only those issues are processed.
    When force=True, delivered fixes are also discarded and regenerated.
    Only issues from the latest analysis per workflow file are targeted.
    """
    authorize_repo(session, current_user, repo_id)
    from app.api.routes.billing import enforce_quota

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
        .where(Analysis.repo_id == repo_id)
        .where(Issue.analysis_id == latest_analysis_subq)
        .where(col(Issue.resolved_at).is_(None))
    )
    if body.issue_ids is not None:
        query = query.where(Issue.id.in_(body.issue_ids))  # type: ignore[attr-defined]
    issues = session.exec(query).all()

    if not issues:
        return {"queued": 0}

    # Group by workflow file → one whole-file fix (one LLM call) per file.
    # The latest-analysis correlation above guarantees workflow_file_id is set.
    by_wf_file: dict[uuid.UUID, list[Issue]] = defaultdict(list)
    for issue in issues:
        by_wf_file[issue.workflow_file_id].append(issue)  # type: ignore[index]

    wf_file_ids = list(by_wf_file)

    # Fixes already attached to the target workflow files are deleted below
    # (or kept and skipped by the worker), so they don't add to the total.
    existing_fix_count = session.exec(
        select(func.count())
        .select_from(Fix)
        .where(col(Fix.workflow_file_id).in_(wf_file_ids))
    ).one()
    enforce_quota(
        session,
        current_user,
        "fixes",
        requested=len(by_wf_file),
        replacing=existing_fix_count,
    )

    delete_stmt = delete(Fix).where(col(Fix.workflow_file_id).in_(wf_file_ids))
    if not force:
        delete_stmt = delete_stmt.where(col(Fix.status) != FixStatus.delivered)
    session.exec(delete_stmt)
    session.commit()

    repo = session.get(Repository, repo_id)
    if repo:
        events_pub.publish_event(
            ev.fix_generating(
                str(repo.org_id),
                str(repo_id),
                fix_ids=[],
                issue_ids=[str(i.id) for i in issues],
            )
        )

    for group in by_wf_file.values():
        run_fix_generation.delay(issue_ids=[str(i.id) for i in group], batch_mode=True)

    return {"queued": len(by_wf_file)}


class WorkflowDeliverRequest(BaseModel):
    fix_id: uuid.UUID


@router.post("/deliver-for-workflow", status_code=202)
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

    pr_body = build_pr_body(
        issues=_issues_info_for_fixes([fix]),
        fix_ids=[str(fix.id)],
        wiki_base_url=settings.WIKI_BASE_URL,
        frontend_host=settings.FRONTEND_HOST,
        bot_handle=settings.GITHUB_BOT_HANDLE,
        app_name=settings.PROJECT_NAME,
        app_url=settings.APP_URL,
    )
    # Stable branch: reuse the branch of the fix's own PR when it has one.
    existing_pr = session.get(PullRequest, fix.pr_id) if fix.pr_id else None
    pr_branch = (
        existing_pr.pr_branch
        if existing_pr
        else f"greensecops/fixes-wf-{str(fix.workflow_file_id)[:8]}"
    )
    deliver_fixes_batch.delay(
        fix_ids=[str(fix.id)],
        repo_id=str(repo.id),
        pr_branch=pr_branch,
        pr_title=f"fix(ci): apply {settings.PROJECT_NAME} fixes for workflow",
        pr_body=pr_body,
        force=force,
    )
    return {"status": "queued"}


@router.post("/deliver-for-repo/{repo_id}", status_code=202)
def trigger_repo_delivery(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    force: bool = False,
) -> dict[str, str]:
    """Deliver all ready fixes for a repo as a single multi-file PR.

    When force=True, fixes in any status are included (not just ready).
    """
    authorize_repo(session, current_user, repo_id)

    base_query = (
        select(Fix)
        .join(WorkflowFile, Fix.workflow_file_id == WorkflowFile.id)  # type: ignore[arg-type]
        .where(WorkflowFile.repo_id == repo_id)
    )
    query = base_query if force else base_query.where(Fix.status == FixStatus.ready)
    fixes = list(session.exec(query).all())
    if not fixes:
        raise HTTPException(status_code=404, detail="No ready fixes found")

    pr_body = build_pr_body(
        issues=_issues_info_for_fixes(fixes),
        fix_ids=[str(f.id) for f in fixes],
        wiki_base_url=settings.WIKI_BASE_URL,
        frontend_host=settings.FRONTEND_HOST,
        bot_handle=settings.GITHUB_BOT_HANDLE,
        app_name=settings.PROJECT_NAME,
        app_url=settings.APP_URL,
    )
    existing_branch = session.exec(
        select(PullRequest.pr_branch)
        .join(Fix, Fix.pr_id == PullRequest.id)  # type: ignore[arg-type]
        .join(WorkflowFile, Fix.workflow_file_id == WorkflowFile.id)  # type: ignore[arg-type]
        .where(WorkflowFile.repo_id == repo_id)
        .order_by(PullRequest.updated_at.desc().nulls_last())  # type: ignore[union-attr]
        .limit(1)
    ).first()
    pr_branch = existing_branch or f"greensecops/fixes-{str(repo_id)[:8]}"
    deliver_fixes_batch.delay(
        fix_ids=[str(f.id) for f in fixes],
        repo_id=str(repo_id),
        pr_branch=pr_branch,
        pr_title=f"fix(ci): apply all {settings.PROJECT_NAME} fixes",
        pr_body=pr_body,
        force=force,
    )
    return {"status": "queued"}


@router.delete("/{fix_id}", status_code=204)
def reject_fix(
    fix_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> None:
    fix = get_or_404(session, Fix, fix_id)
    _authorize_fix(session, current_user, fix)
    fix.status = FixStatus.rejected
    session.add(fix)
    session.commit()

    wf_file = session.get(WorkflowFile, fix.workflow_file_id)
    repo = session.get(Repository, wf_file.repo_id) if wf_file else None
    if repo:
        events_pub.publish_event(
            ev.fix_rejected(str(repo.org_id), str(repo.id), str(fix_id))
        )


@router.post("/regenerate-for-pr/{pr_id}", status_code=202)
def regenerate_fixes_for_pr(
    pr_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, int]:
    """Delete delivered fixes for a closed PR and re-trigger generation.

    Only valid when pr_state == closed. Merged PRs are not touched because
    the code changes were already applied.
    """
    pr = get_or_404(session, PullRequest, pr_id)
    if not current_user.is_superuser:
        authorize_repo(
            session, current_user, pr.repo_id, detail="PullRequest not found"
        )
    if pr.pr_state != PullRequestState.closed:
        raise HTTPException(
            status_code=409,
            detail=f"PR is not closed (state: {pr.pr_state})",
        )

    fixes = list(session.exec(select(Fix).where(Fix.pr_id == pr_id)).all())
    if not fixes:
        return {"queued": 0}

    # Regenerate the unresolved issues each fix addressed, per workflow file.
    issue_groups: list[list[uuid.UUID]] = []
    for fix in fixes:
        issue_ids = list(
            session.exec(
                select(Issue.id)
                .where(Issue.fix_id == fix.id)
                .where(col(Issue.resolved_at).is_(None))
            ).all()
        )
        if issue_ids:
            issue_groups.append(issue_ids)

    fix_ids_to_delete = [fix.id for fix in fixes]
    session.exec(delete(Fix).where(Fix.id.in_(fix_ids_to_delete)))  # type: ignore[attr-defined]
    session.commit()

    all_issue_ids = [iid for ids in issue_groups for iid in ids]

    repo = session.get(Repository, pr.repo_id)
    if repo:
        events_pub.publish_event(
            ev.fix_generating(
                str(repo.org_id),
                str(repo.id),
                fix_ids=[],
                issue_ids=[str(iid) for iid in all_issue_ids],
            )
        )

    for issue_ids in issue_groups:
        run_fix_generation.delay(
            issue_ids=[str(iid) for iid in issue_ids],
            batch_mode=True,
        )

    return {"queued": len(all_issue_ids)}


@router.post("/sync-pr-status/{repo_id}")
async def sync_pr_statuses(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    github_client: GitHubAppClientDep,
) -> dict[str, int]:
    repo = authorize_repo(session, current_user, repo_id)

    open_prs = list(
        session.exec(
            select(PullRequest)
            .where(PullRequest.repo_id == repo_id)
            .where(PullRequest.pr_url.is_not(None))  # type: ignore[union-attr]
            .where(PullRequest.pr_state == PullRequestState.open)
        ).all()
    )
    if not open_prs:
        return {"synced": 0, "updated": 0}

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

        pr_record.pr_state = new_state
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

    return {"synced": len(open_prs), "updated": updated}
