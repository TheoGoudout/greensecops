import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Analysis,
    Fix,
    FixStatus,
    Issue,
    IssueCategory,
    IssuePublic,
    IssueSeverity,
)


def _to_issue_public(issue: Issue) -> IssuePublic:
    fix = issue.fix
    return IssuePublic(
        id=issue.id,
        analysis_id=issue.analysis_id,
        rule_id=issue.rule_id,
        rule_slug=issue.rule.slug if issue.rule else "",
        severity=issue.severity,
        category=issue.category,
        line_start=issue.line_start,
        line_end=issue.line_end,
        message=issue.message,
        context=issue.context,
        created_at=issue.created_at,
        fix_id=fix.id if fix else None,
        fix_status=fix.status if fix else None,
    )


router = APIRouter(prefix="/issues", tags=["issues"])


@router.get("/", response_model=list[IssuePublic])
def list_issues(
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
    analysis_id: uuid.UUID | None = None,
    repo_id: uuid.UUID | None = None,
    category: IssueCategory | None = None,
    severity: IssueSeverity | None = None,
    unfixed: bool = False,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, le=500),
) -> list[IssuePublic]:
    query = select(Issue)
    if analysis_id:
        query = query.where(Issue.analysis_id == analysis_id)
    if repo_id:
        query = query.join(Analysis, Issue.analysis_id == Analysis.id).where(  # type: ignore[arg-type]
            Analysis.repo_id == repo_id
        )
    if unfixed:
        active_fix_issue_ids = select(Fix.issue_id).where(
            Fix.status != FixStatus.rejected
        )
        query = query.where(~Issue.id.in_(active_fix_issue_ids))  # type: ignore[attr-defined]
    if category:
        query = query.where(Issue.category == category)
    if severity:
        query = query.where(Issue.severity == severity)
    query = query.order_by(Issue.created_at.desc()).offset(skip).limit(limit)  # type: ignore[arg-type]
    return [_to_issue_public(issue) for issue in session.exec(query).all()]


@router.get("/{issue_id}", response_model=IssuePublic)
def get_issue(
    issue_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
) -> IssuePublic:
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return _to_issue_public(issue)
