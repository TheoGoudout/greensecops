import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.models import Issue, IssueCategory, IssuePublic, IssueSeverity

router = APIRouter(prefix="/issues", tags=["issues"])


@router.get("/", response_model=list[IssuePublic])
def list_issues(
    session: SessionDep,
    current_user: CurrentUser,
    analysis_id: uuid.UUID | None = None,
    category: IssueCategory | None = None,
    severity: IssueSeverity | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, le=500),
) -> list[Issue]:
    query = select(Issue)
    if analysis_id:
        query = query.where(Issue.analysis_id == analysis_id)
    if category:
        query = query.where(Issue.category == category)
    if severity:
        query = query.where(Issue.severity == severity)
    query = query.order_by(Issue.created_at.desc()).offset(skip).limit(limit)  # type: ignore[arg-type]
    return list(session.exec(query).all())


@router.get("/{issue_id}", response_model=IssuePublic)
def get_issue(
    issue_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Issue:
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue
