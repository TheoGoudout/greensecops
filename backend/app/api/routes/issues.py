import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep, get_or_404, user_org_ids
from app.api.mappers import to_issue_public
from app.models import (
    Analysis,
    AnalysisStatus,
    Fix,
    Issue,
    IssueCategory,
    IssuePublic,
    IssueSeverity,
    Repository,
    WorkflowFile,
)
from app.services.state_machines import REJECTED_STATUSES

router = APIRouter(prefix="/issues", tags=["issues"])


def _authorize_issue(
    session: SessionDep, current_user: CurrentUser, issue: Issue
) -> None:
    """404 unless the caller is a superuser or a member of the issue's org."""
    if current_user.is_superuser:
        return
    analysis = session.get(Analysis, issue.analysis_id)
    repo = session.get(Repository, analysis.repo_id) if analysis else None
    if not repo or repo.org_id not in user_org_ids(session, current_user):
        raise HTTPException(status_code=404, detail="Issue not found")


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
    include_ignored: bool = False,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, le=500),
) -> list[IssuePublic]:
    query = select(Issue)
    if not include_resolved:
        query = query.where(col(Issue.resolved_at).is_(None))
    if not include_ignored:
        query = query.where(col(Issue.ignored_at).is_(None))
    # Issues belong to a per-branch WorkflowFile row; a repo listing without an
    # explicit branch shows the default branch (feature-branch issues only
    # appear when asked for).
    if repo_id is not None and branch is None:
        repo = session.get(Repository, repo_id)
        branch = repo.default_branch if repo else None
    # Join Analysis once if either tenant scoping or repo filtering needs it.
    needs_analysis_join = repo_id is not None or not current_user.is_superuser
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
        query = query.join(
            WorkflowFile,
            Issue.workflow_file_id == WorkflowFile.id,  # type: ignore[arg-type]
        ).where(WorkflowFile.branch == branch)
    if repo_id:
        query = query.where(Analysis.repo_id == repo_id)
        if latest_only:
            # The workflow_file_id correlation is inherently branch-scoped now
            # that WorkflowFile rows are per-branch.
            latest_subq = (
                select(Analysis.id)
                .where(Analysis.workflow_file_id == Issue.workflow_file_id)
                .where(Analysis.status == AnalysisStatus.completed)
                .order_by(
                    Analysis.completed_at.desc().nulls_last(),
                    Analysis.created_at.desc(),
                )  # type: ignore[union-attr]
                .limit(1)
                .correlate(Issue)
                .scalar_subquery()
            )
            query = query.where(Issue.analysis_id == latest_subq)
    if unfixed:
        active_fix_ids = select(Fix.id).where(col(Fix.status).not_in(REJECTED_STATUSES))
        query = query.where(
            col(Issue.fix_id).is_(None) | ~col(Issue.fix_id).in_(active_fix_ids)
        )
    if category:
        query = query.where(Issue.category == category)
    if severity:
        query = query.where(Issue.severity == severity)
    severity_rank = case(
        (Issue.severity == IssueSeverity.critical, 0),
        (Issue.severity == IssueSeverity.high, 1),
        (Issue.severity == IssueSeverity.medium, 2),
        (Issue.severity == IssueSeverity.low, 3),
        (Issue.severity == IssueSeverity.info, 4),
        else_=99,
    )
    query = (
        query.order_by(severity_rank, Issue.created_at.desc()).offset(skip).limit(limit)
    )  # type: ignore[arg-type]
    return [to_issue_public(issue) for issue in session.exec(query).all()]


@router.get("/{issue_id}", response_model=IssuePublic)
def get_issue(
    issue_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> IssuePublic:
    issue = get_or_404(session, Issue, issue_id)
    _authorize_issue(session, current_user, issue)
    return to_issue_public(issue)


@router.post("/{issue_id}/ignore", response_model=IssuePublic)
def ignore_issue(
    issue_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> IssuePublic:
    """Mute a violation (false positive / accepted risk).

    Sets ``ignored_at``; the DB trigger recomputes ``status`` to ``ignored``,
    which takes precedence over resolve/fix state and drops the issue out of the
    default (active) issue and fix queries. Idempotent.
    """
    issue = get_or_404(session, Issue, issue_id)
    _authorize_issue(session, current_user, issue)
    if issue.ignored_at is None:
        issue.ignored_at = datetime.now(timezone.utc)
        session.add(issue)
        session.commit()
        session.refresh(issue)
    return to_issue_public(issue)


@router.post("/{issue_id}/unignore", response_model=IssuePublic)
def unignore_issue(
    issue_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> IssuePublic:
    """Un-mute a previously ignored violation. Idempotent."""
    issue = get_or_404(session, Issue, issue_id)
    _authorize_issue(session, current_user, issue)
    if issue.ignored_at is not None:
        issue.ignored_at = None
        session.add(issue)
        session.commit()
        session.refresh(issue)
    return to_issue_public(issue)
