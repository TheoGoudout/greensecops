import difflib
import time
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
from app.services.pr_body import IssueInfo, build_pr_body
from app.workers.tasks.fix_delivery import deliver_fix, deliver_fixes_batch
from app.workers.tasks.fix_generation import (
    run_batch_fix_generation,
    run_fix_generation,
)


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
) -> list[Fix]:
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
    return list(session.exec(query).all())


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
) -> dict[str, int]:
    """Queue a single batch fix generation call per workflow file for issues in a repo.

    When body.issue_ids is provided, only those issues are processed.
    """
    query = (
        select(Issue)
        .join(Analysis, Issue.analysis_id == Analysis.id)  # type: ignore[arg-type]
        .where(Analysis.repo_id == repo_id)
    )
    if body.issue_ids is not None:
        query = query.where(Issue.id.in_(body.issue_ids))  # type: ignore[attr-defined]
    issues = session.exec(query).all()

    if not issues:
        return {"queued": 0}

    issue_ids = [i.id for i in issues]

    # Discard existing non-delivered fixes to allow fresh retry
    session.exec(
        delete(Fix).where(
            Fix.issue_id.in_(issue_ids),  # type: ignore[attr-defined]
            Fix.status != FixStatus.delivered,
        )
    )
    session.commit()

    # Group by analysis_id → one LLM call per workflow file
    by_analysis: dict[uuid.UUID, list[Issue]] = defaultdict(list)
    for issue in issues:
        by_analysis[issue.analysis_id].append(issue)

    for group in by_analysis.values():
        run_batch_fix_generation.delay(issue_ids=[str(i.id) for i in group])

    return {"queued": len(issues)}


@router.post("/generate/{issue_id}", status_code=202)
def trigger_fix_generation(
    issue_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
) -> dict[str, str]:
    get_or_404(session, Issue, issue_id)

    # Discard existing non-delivered fix to allow retry
    session.exec(
        delete(Fix).where(
            Fix.issue_id == issue_id,
            Fix.status != FixStatus.delivered,
        )
    )
    session.commit()

    run_fix_generation.delay(issue_id=str(issue_id))
    return {"status": "queued", "issue_id": str(issue_id)}


@router.post("/{fix_id}/deliver", status_code=202)
def trigger_fix_delivery(
    fix_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
) -> dict[str, str]:
    fix = get_or_404(session, Fix, fix_id)
    if fix.status != FixStatus.ready:
        raise HTTPException(
            status_code=409, detail=f"Fix is not ready (status: {fix.status})"
        )
    deliver_fix.delay(fix_id=str(fix_id))
    return {"status": "queued", "fix_id": str(fix_id)}


class WorkflowDeliverRequest(BaseModel):
    fix_ids: list[uuid.UUID]


@router.post("/deliver-for-workflow", status_code=202)
def trigger_workflow_delivery(
    body: WorkflowDeliverRequest,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
) -> dict[str, str]:
    """Deliver all ready fixes for one workflow file as a single PR."""
    fixes = [session.get(Fix, fid) for fid in body.fix_ids]
    fixes = [f for f in fixes if f and f.status == FixStatus.ready]
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
    )
    pr_branch = f"greensecops/fixes-wf-{fixes[0].id!s:.8}"
    deliver_fixes_batch.delay(
        fix_ids=[str(f.id) for f in fixes],
        repo_id=str(repo.id),
        pr_branch=pr_branch,
        pr_title="fix(ci): apply GreenSecOps fixes for workflow",
        pr_body=pr_body,
    )
    return {"status": "queued"}


@router.post("/deliver-for-repo/{repo_id}", status_code=202)
def trigger_repo_delivery(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
) -> dict[str, str]:
    """Deliver all ready fixes for a repo as a single multi-file PR."""
    repo = session.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    query = (
        select(Fix)
        .join(Issue, Fix.issue_id == Issue.id)  # type: ignore[arg-type]
        .join(Analysis, Issue.analysis_id == Analysis.id)  # type: ignore[arg-type]
        .where(Analysis.repo_id == repo_id, Fix.status == FixStatus.ready)
    )
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
    )
    pr_branch = f"greensecops/fixes-{int(time.time())}"
    deliver_fixes_batch.delay(
        fix_ids=[str(f.id) for f in fixes],
        repo_id=str(repo_id),
        pr_branch=pr_branch,
        pr_title="fix(ci): apply all GreenSecOps fixes",
        pr_body=pr_body,
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
