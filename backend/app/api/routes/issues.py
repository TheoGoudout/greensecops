import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep, get_or_404, user_org_ids
from app.api.mappers import to_issue_public
from app.models import (
    Analysis,
    AnalysisStatus,
    Fix,
    FixStatus,
    Issue,
    IssueCategory,
    IssuePublic,
    IssueSeverity,
    Repository,
)

router = APIRouter(prefix="/issues", tags=["issues"])


@router.get("/", response_model=list[IssuePublic])
def list_issues(
    session: SessionDep,
    current_user: CurrentUser,
    analysis_id: uuid.UUID | None = None,
    repo_id: uuid.UUID | None = None,
    branch: str | None = None,
    category: IssueCategory | None = None,
    severity: IssueSeverity | None = None,
    unfixed: bool = False,
    latest_only: bool = True,
    include_resolved: bool = False,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, le=500),
) -> list[IssuePublic]:
    query = select(Issue)
    if not include_resolved:
        query = query.where(col(Issue.resolved_at).is_(None))
    # Join Analysis once if either tenant scoping or repo/branch filtering needs it.
    needs_analysis_join = (
        repo_id is not None or branch is not None or not current_user.is_superuser
    )
    if needs_analysis_join:
        query = query.join(Analysis, Issue.analysis_id == Analysis.id)  # type: ignore[arg-type]
    if not current_user.is_superuser:
        query = query.where(
            Analysis.repo_id.in_(  # type: ignore[attr-defined]
                select(Repository.id).where(
                    Repository.org_id.in_(user_org_ids(session, current_user))  # type: ignore[attr-defined]
                )
            )
        )
    if analysis_id:
        query = query.where(Issue.analysis_id == analysis_id)
    if branch:
        query = query.where(Analysis.branch == branch)
    if repo_id:
        query = query.where(Analysis.repo_id == repo_id)
        if latest_only:
            latest_subq = (
                select(Analysis.id)
                .where(Analysis.workflow_file_id == Issue.workflow_file_id)
                .where(Analysis.status == AnalysisStatus.completed)
            )
            if branch:
                latest_subq = latest_subq.where(Analysis.branch == branch)
            latest_subq = (
                latest_subq.order_by(
                    Analysis.completed_at.desc().nulls_last(),
                    Analysis.created_at.desc(),
                )  # type: ignore[union-attr]
                .limit(1)
                .correlate(Issue)
                .scalar_subquery()
            )
            query = query.where(Issue.analysis_id == latest_subq)
    if unfixed:
        active_fix_ids = select(Fix.id).where(Fix.status != FixStatus.rejected)
        query = query.where(
            col(Issue.fix_id).is_(None) | ~col(Issue.fix_id).in_(active_fix_ids)
        )
    if category:
        query = query.where(Issue.category == category)
    if severity:
        query = query.where(Issue.severity == severity)
    query = query.order_by(Issue.created_at.desc()).offset(skip).limit(limit)  # type: ignore[arg-type]
    return [to_issue_public(issue) for issue in session.exec(query).all()]


@router.get("/{issue_id}", response_model=IssuePublic)
def get_issue(
    issue_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> IssuePublic:
    issue = get_or_404(session, Issue, issue_id)
    if not current_user.is_superuser:
        analysis = session.get(Analysis, issue.analysis_id)
        repo = session.get(Repository, analysis.repo_id) if analysis else None
        if not repo or repo.org_id not in user_org_ids(session, current_user):
            raise HTTPException(status_code=404, detail="Issue not found")
    return to_issue_public(issue)
