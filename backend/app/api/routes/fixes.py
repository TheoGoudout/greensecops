import difflib
import uuid
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import delete, select

from app.api.deps import CurrentUser, SessionDep, get_or_404
from app.core.config import settings
from app.models import (
    Analysis,
    Fix,
    FixPublic,
    FixStatus,
    Issue,
    Repository,
    WorkflowFile,
)
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.services.pr_body import IssueInfo, build_pr_body
from app.workers.tasks.fix_delivery import deliver_fix, deliver_fixes_batch
from app.workers.tasks.fix_generation import run_fix_generation


class BatchFixRequest(BaseModel):
    issue_ids: list[uuid.UUID] | None = None


router = APIRouter(prefix="/fixes", tags=["fixes"])


@router.get("/", response_model=list[FixPublic])
def list_fixes(
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
    issue_id: uuid.UUID | None = None,
    analysis_id: uuid.UUID | None = None,
    repo_id: uuid.UUID | None = None,
    status: FixStatus | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
) -> list[FixPublic]:
    query = select(Fix)
    if issue_id:
        query = query.where(Fix.issue_id == issue_id)
    if analysis_id or repo_id:
        query = query.join(Issue, Fix.issue_id == Issue.id)  # type: ignore[arg-type]
        if analysis_id:
            query = query.where(Issue.analysis_id == analysis_id)
        if repo_id:
            query = query.join(Analysis, Issue.analysis_id == Analysis.id).where(  # type: ignore[arg-type]
                Analysis.repo_id == repo_id
            )
    if status:
        query = query.where(Fix.status == status)
    query = query.order_by(Fix.created_at.desc()).offset(skip).limit(limit)  # type: ignore[arg-type]
    fixes = list(session.exec(query).all())

    # Bulk-load workflow files to compute diff_patch without N+1 queries
    fixes_with_diff = [f for f in fixes if f.diff]
    fix_to_wf: dict[uuid.UUID, WorkflowFile] = {}
    if fixes_with_diff:
        issue_ids = [f.issue_id for f in fixes_with_diff]
        issues_map = {
            i.id: i
            for i in session.exec(select(Issue).where(Issue.id.in_(issue_ids))).all()  # type: ignore[arg-type]
        }
        analysis_ids = list(
            {i.analysis_id for i in issues_map.values() if i.analysis_id}
        )
        analyses_map = {
            a.id: a
            for a in session.exec(
                select(Analysis).where(Analysis.id.in_(analysis_ids))
            ).all()  # type: ignore[arg-type]
        }
        wf_file_ids = list(
            {a.workflow_file_id for a in analyses_map.values() if a.workflow_file_id}
        )
        wf_files_map = {
            w.id: w
            for w in session.exec(
                select(WorkflowFile).where(WorkflowFile.id.in_(wf_file_ids))  # type: ignore[arg-type]
            ).all()
        }
        for fix in fixes_with_diff:
            issue = issues_map.get(fix.issue_id)
            analysis = (
                analyses_map.get(issue.analysis_id)
                if issue and issue.analysis_id
                else None
            )
            wf_file = (
                wf_files_map.get(analysis.workflow_file_id)
                if analysis and analysis.workflow_file_id
                else None
            )
            if wf_file:
                fix_to_wf[fix.id] = wf_file

    result: list[FixPublic] = []
    for fix in fixes:
        data = FixPublic.model_validate(fix)
        wf_file = fix_to_wf.get(fix.id)
        if fix.diff and wf_file and wf_file.raw_content:
            fixed = fix.diff if fix.diff.endswith("\n") else fix.diff + "\n"
            patch = "".join(
                difflib.unified_diff(
                    wf_file.raw_content.splitlines(keepends=True),
                    fixed.splitlines(keepends=True),
                    fromfile=f"a/{wf_file.path}",
                    tofile=f"b/{wf_file.path}",
                )
            )
            data.diff_patch = patch or None
        result.append(data)
    return result


@router.get("/{fix_id}", response_model=FixPublic)
def get_fix(
    fix_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
) -> FixPublic:
    fix = get_or_404(session, Fix, fix_id)
    data = FixPublic.model_validate(fix)

    if fix.diff:
        issue = session.get(Issue, fix.issue_id)
        analysis = session.get(Analysis, issue.analysis_id) if issue else None
        wf_file = (
            session.get(WorkflowFile, analysis.workflow_file_id) if analysis else None
        )
        if wf_file and wf_file.raw_content:
            original = wf_file.raw_content
            fixed = fix.diff if fix.diff.endswith("\n") else fix.diff + "\n"
            original_lines = original.splitlines(keepends=True)
            fixed_lines = fixed.splitlines(keepends=True)
            patch = "".join(
                difflib.unified_diff(
                    original_lines,
                    fixed_lines,
                    fromfile=f"a/{wf_file.path}",
                    tofile=f"b/{wf_file.path}",
                )
            )
            data.diff_patch = patch or None

    return data


@router.post("/generate-for-repo/{repo_id}", status_code=202)
def trigger_fix_generation_for_repo(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
    body: BatchFixRequest = BatchFixRequest(),
    force: bool = False,
) -> dict[str, int]:
    """Queue a single batch fix generation call per workflow file for issues in a repo.

    When body.issue_ids is provided, only those issues are processed.
    When force=True, delivered fixes are also discarded and regenerated.
    Only issues from the latest analysis per workflow file are targeted.
    """
    latest_ids = select(WorkflowFile.latest_analysis_id).where(
        WorkflowFile.repo_id == repo_id,
        WorkflowFile.latest_analysis_id.is_not(None),  # type: ignore[union-attr]
    )
    query = (
        select(Issue)
        .join(Analysis, Issue.analysis_id == Analysis.id)  # type: ignore[arg-type]
        .where(Analysis.repo_id == repo_id)
        .where(Issue.analysis_id.in_(latest_ids))  # type: ignore[attr-defined]
    )
    if body.issue_ids is not None:
        query = query.where(Issue.id.in_(body.issue_ids))  # type: ignore[attr-defined]
    issues = session.exec(query).all()

    if not issues:
        return {"queued": 0}

    issue_ids = [i.id for i in issues]

    delete_stmt = delete(Fix).where(Fix.issue_id.in_(issue_ids))  # type: ignore[attr-defined]
    if not force:
        delete_stmt = delete_stmt.where(Fix.status != FixStatus.delivered)
    session.exec(delete_stmt)
    session.commit()

    # Group by analysis_id → one LLM call per workflow file
    by_analysis: dict[uuid.UUID, list[Issue]] = defaultdict(list)
    for issue in issues:
        by_analysis[issue.analysis_id].append(issue)

    for group in by_analysis.values():
        run_fix_generation.delay(issue_ids=[str(i.id) for i in group])

    return {"queued": len(issues)}


@router.post("/generate/{issue_id}", status_code=202)
def trigger_fix_generation(
    issue_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
    force: bool = False,
) -> dict[str, str]:
    get_or_404(session, Issue, issue_id)

    delete_stmt = delete(Fix).where(Fix.issue_id == issue_id)
    if not force:
        delete_stmt = delete_stmt.where(Fix.status != FixStatus.delivered)
    session.exec(delete_stmt)
    session.commit()

    run_fix_generation.delay(issue_ids=[str(issue_id)])
    return {"status": "queued", "issue_id": str(issue_id)}


@router.post("/{fix_id}/deliver", status_code=202)
def trigger_fix_delivery(
    fix_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
    force: bool = False,
) -> dict[str, str]:
    fix = get_or_404(session, Fix, fix_id)
    if not force and fix.status != FixStatus.ready:
        raise HTTPException(
            status_code=409, detail=f"Fix is not ready (status: {fix.status})"
        )
    deliver_fix.delay(fix_id=str(fix_id), force=force)
    return {"status": "queued", "fix_id": str(fix_id)}


class WorkflowDeliverRequest(BaseModel):
    fix_ids: list[uuid.UUID]


@router.post("/deliver-for-workflow", status_code=202)
def trigger_workflow_delivery(
    body: WorkflowDeliverRequest,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
    force: bool = False,
) -> dict[str, str]:
    """Deliver all ready fixes for one workflow file as a single PR.

    When force=True, fixes in any status are included (not just ready).
    """
    fixes = [session.get(Fix, fid) for fid in body.fix_ids]
    fixes = [f for f in fixes if f and (force or f.status == FixStatus.ready)]
    if not fixes:
        raise HTTPException(status_code=404, detail="No ready fixes found")

    issue = fixes[0].issue
    analysis = issue.analysis if issue else None
    repo = session.get(Repository, analysis.repo_id) if analysis else None
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    issues_info = [
        IssueInfo(
            rule_slug=fix.issue.rule.slug if fix.issue and fix.issue.rule else "fix",
            rule_title=fix.issue.rule.title if fix.issue and fix.issue.rule else "Fix",
            category=fix.issue.category.value
            if fix.issue and fix.issue.category
            else "unknown",
            severity=fix.issue.severity.value
            if fix.issue and fix.issue.severity
            else "unknown",
            message=fix.issue.message or "" if fix.issue else "",
        )
        for fix in fixes
        if fix.issue
    ]
    pr_body = build_pr_body(
        issues=issues_info,
        fix_ids=[str(f.id) for f in fixes],
        wiki_base_url=settings.WIKI_BASE_URL,
        frontend_host=settings.FRONTEND_HOST,
        bot_handle=settings.GITHUB_BOT_HANDLE,
        app_name=settings.PROJECT_NAME,
        app_url=settings.APP_URL,
    )
    # Stable branch: reuse existing pr_branch if set, else derive from workflow file id.
    existing_branch = next((f.pr_branch for f in fixes if f.pr_branch), None)
    wf_id = (
        fixes[0].issue.analysis.workflow_file_id
        if fixes[0].issue and fixes[0].issue.analysis
        else None
    )
    pr_branch = existing_branch or (
        f"greensecops/fixes-wf-{str(wf_id)[:8]}"
        if wf_id
        else f"greensecops/fixes-wf-{fixes[0].id!s:.8}"
    )
    deliver_fixes_batch.delay(
        fix_ids=[str(f.id) for f in fixes],
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
    current_user: CurrentUser,  # noqa: ARG001
    force: bool = False,
) -> dict[str, str]:
    """Deliver all ready fixes for a repo as a single multi-file PR.

    When force=True, fixes in any status are included (not just ready).
    """
    repo = session.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    base_query = (
        select(Fix)
        .join(Issue, Fix.issue_id == Issue.id)  # type: ignore[arg-type]
        .join(Analysis, Issue.analysis_id == Analysis.id)  # type: ignore[arg-type]
        .where(Analysis.repo_id == repo_id)
    )
    query = base_query if force else base_query.where(Fix.status == FixStatus.ready)
    fixes = list(session.exec(query).all())
    if not fixes:
        raise HTTPException(status_code=404, detail="No ready fixes found")

    issues_info = [
        IssueInfo(
            rule_slug=fix.issue.rule.slug if fix.issue and fix.issue.rule else "fix",
            rule_title=fix.issue.rule.title if fix.issue and fix.issue.rule else "Fix",
            category=fix.issue.category.value
            if fix.issue and fix.issue.category
            else "unknown",
            severity=fix.issue.severity.value
            if fix.issue and fix.issue.severity
            else "unknown",
            message=fix.issue.message or "" if fix.issue else "",
        )
        for fix in fixes
        if fix.issue
    ]
    pr_body = build_pr_body(
        issues=issues_info,
        fix_ids=[str(f.id) for f in fixes],
        wiki_base_url=settings.WIKI_BASE_URL,
        frontend_host=settings.FRONTEND_HOST,
        bot_handle=settings.GITHUB_BOT_HANDLE,
        app_name=settings.PROJECT_NAME,
        app_url=settings.APP_URL,
    )
    existing_branch = next((f.pr_branch for f in fixes if f.pr_branch), None)
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
    current_user: CurrentUser,  # noqa: ARG001
) -> None:
    fix = get_or_404(session, Fix, fix_id)
    fix.status = FixStatus.rejected
    session.add(fix)
    session.commit()

    issue = session.get(Issue, fix.issue_id)
    analysis = session.get(Analysis, issue.analysis_id) if issue else None
    repo = session.get(Repository, analysis.repo_id) if analysis else None
    if repo:
        events_pub.publish_event(
            ev.fix_rejected(str(repo.org_id), str(repo.id), str(fix_id))
        )
