import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException, Query
from sqlalchemy import case, func
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep, get_or_404, user_org_ids
from app.api.mappers import to_issue_public
from app.api.router import Role, RoleRouter
from app.models import (
    Analysis,
    AnalysisStatus,
    Category,
    Fix,
    Issue,
    IssueCategoryStat,
    IssuePublic,
    IssueStatsPublic,
    RepoCategoryStat,
    RepoIssueStats,
    Repository,
    Rule,
    Severity,
    WorkflowFile,
)
from app.services.scoring import (
    compute_avg_scores_batch,
    compute_category_scores,
    score_to_grade,
    severity_penalty_case,
)
from app.services.state_machines import REJECTED_STATUSES

router = RoleRouter(prefix="/issues", tags=["issues"])


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


@router.get("/", role=Role.user, response_model=list[IssuePublic])
def list_issues(
    session: SessionDep,
    current_user: CurrentUser,
    analysis_id: uuid.UUID | None = None,
    repo_id: uuid.UUID | None = None,
    branch: str | None = None,
    category: Category | None = None,
    severity: Severity | None = None,
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
        # that WorkflowFile rows are per-branch. Applies regardless of repo_id
        # scoping so org-wide listings (e.g. the dashboard) don't count stale
        # issue rows left over from a workflow file's earlier analyses.
        latest_subq = (
            select(Analysis.id)
            .where(Analysis.workflow_file_id == Issue.workflow_file_id)
            .where(Analysis.status == AnalysisStatus.completed)
            .order_by(
                col(Analysis.completed_at).desc().nulls_last(),
                col(Analysis.created_at).desc(),
            )
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
        (col(Issue.severity) == Severity.critical, 0),
        (col(Issue.severity) == Severity.high, 1),
        (col(Issue.severity) == Severity.medium, 2),
        (col(Issue.severity) == Severity.low, 3),
        (col(Issue.severity) == Severity.info, 4),
        else_=99,
    )
    query = (
        query.order_by(severity_rank, col(Issue.created_at).desc())
        .offset(skip)
        .limit(limit)
    )
    return [to_issue_public(issue) for issue in session.exec(query).all()]


@router.get("/stats", role=Role.user, response_model=IssueStatsPublic)
def get_issue_stats(
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID | None = None,
    branch: str | None = None,
    latest_only: bool = True,
) -> IssueStatsPublic:
    """Exact open/resolved issue counts by category, aggregated in SQL.

    Powers the dashboard's stat cards and category health breakdown without
    the pagination cap a plain ``list_issues`` fetch would hit on a large
    org — every matching row is summed server-side, never materialized into
    a capped page of ``IssuePublic`` objects.
    """
    query = select(Issue).where(col(Issue.ignored_at).is_(None))

    if repo_id is not None and branch is None:
        repo = session.get(Repository, repo_id)
        branch = repo.default_branch if repo else None

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
    if branch:
        query = query.join(
            WorkflowFile,
            Issue.workflow_file_id == WorkflowFile.id,  # type: ignore[arg-type]
        ).where(WorkflowFile.branch == branch)
    if repo_id:
        query = query.where(Analysis.repo_id == repo_id)
    if latest_only:
        latest_subq = (
            select(Analysis.id)
            .where(Analysis.workflow_file_id == Issue.workflow_file_id)
            .where(Analysis.status == AnalysisStatus.completed)
            .order_by(
                col(Analysis.completed_at).desc().nulls_last(),
                col(Analysis.created_at).desc(),
            )
            .limit(1)
            .correlate(Issue)
            .scalar_subquery()
        )
        query = query.where(Issue.analysis_id == latest_subq)

    is_open = col(Issue.resolved_at).is_(None)
    is_critical = Issue.severity == Severity.critical
    grouped = query.with_only_columns(  # type: ignore[call-overload]
        Issue.category,
        func.sum(case((is_open, 1), else_=0)).label("open"),
        func.sum(case((~is_open, 1), else_=0)).label("resolved"),
        func.sum(case((is_open & is_critical, 1), else_=0)).label("critical_open"),
    ).group_by(Issue.category)

    # session.exec() would scalarize this to just the first column: the
    # original select(Issue) statement stays a sqlmodel SelectOfScalar even
    # after with_only_columns() swaps in the aggregate columns. session.execute()
    # (the underlying SQLAlchemy call) returns full Row tuples instead.
    by_category = [
        IssueCategoryStat(
            category=row.category,
            open=row.open or 0,
            resolved=row.resolved or 0,
            critical_open=row.critical_open or 0,
        )
        for row in session.execute(grouped).all()
    ]

    # Per-repo breakdown for the dashboard's category health star diagram.
    # Only meaningful when not already scoped to a single repo; needs
    # Analysis (and Rule, for severity_weight) joined regardless of the
    # superuser/org-filter branch above.
    by_repo: list[RepoIssueStats] = []
    if repo_id is None:
        repo_query = (
            query
            if needs_analysis_join
            else query.join(Analysis, Issue.analysis_id == Analysis.id)  # type: ignore[arg-type]
        )
        repo_query = repo_query.join(Rule, Issue.rule_id == Rule.id)  # type: ignore[arg-type]
        repo_grouped = repo_query.with_only_columns(  # type: ignore[call-overload]
            Analysis.repo_id,
            Issue.category,
            func.sum(case((is_open, 1), else_=0)).label("open"),
            func.sum(case((is_open & is_critical, 1), else_=0)).label("critical_open"),
            func.sum(
                case(
                    (
                        is_open,
                        severity_penalty_case(col(Issue.severity))
                        * Rule.severity_weight,
                    ),
                    else_=0.0,
                )
            ).label("weighted_penalty"),
        ).group_by(Analysis.repo_id, Issue.category)
        rows = session.execute(repo_grouped).all()

        counts_by_repo: dict[uuid.UUID, dict[Category, tuple[int, int]]] = defaultdict(
            dict
        )
        penalties_by_repo: dict[uuid.UUID, dict[Category, float]] = defaultdict(
            lambda: dict.fromkeys(Category, 0.0)
        )
        for row in rows:
            counts_by_repo[row.repo_id][row.category] = (
                row.open or 0,
                row.critical_open or 0,
            )
            penalties_by_repo[row.repo_id][row.category] = row.weighted_penalty or 0.0

        # Only repos with at least one matching issue appear here; a repo
        # with none gets no row at all, and the frontend falls back to that
        # repo's own overall score for every axis (all-clean pentagon).
        repo_ids = sorted(counts_by_repo, key=str)
        avg_scores = compute_avg_scores_batch(session, repo_ids)

        for repo_id_ in repo_ids:
            repo_avg_score = avg_scores.get(repo_id_)
            category_scores = (
                compute_category_scores(repo_avg_score, penalties_by_repo[repo_id_])
                if repo_avg_score is not None
                else {}
            )
            categories = [
                RepoCategoryStat(
                    category=category,
                    open=counts_by_repo[repo_id_].get(category, (0, 0))[0],
                    critical_open=counts_by_repo[repo_id_].get(category, (0, 0))[1],
                    score=category_scores.get(category, (None, None))[0],
                    grade=category_scores.get(category, (None, None))[1],
                )
                for category in Category
            ]
            by_repo.append(
                RepoIssueStats(
                    repo_id=repo_id_,
                    score=round(repo_avg_score, 1)
                    if repo_avg_score is not None
                    else None,
                    grade=score_to_grade(repo_avg_score)
                    if repo_avg_score is not None
                    else None,
                    categories=categories,
                )
            )

    return IssueStatsPublic(
        total_open=sum(r.open for r in by_category),
        total_resolved=sum(r.resolved for r in by_category),
        critical_open=sum(r.critical_open for r in by_category),
        by_category=by_category,
        by_repo=by_repo,
    )


@router.get("/{issue_id}", role=Role.org_member, response_model=IssuePublic)
def get_issue(
    issue_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> IssuePublic:
    issue = get_or_404(session, Issue, issue_id)
    _authorize_issue(session, current_user, issue)
    return to_issue_public(issue)


@router.post("/{issue_id}/ignore", role=Role.org_admin, response_model=IssuePublic)
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


@router.post("/{issue_id}/unignore", role=Role.org_admin, response_model=IssuePublic)
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
