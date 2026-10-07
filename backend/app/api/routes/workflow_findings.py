import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Query
from sqlalchemy import case, func
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep, get_or_404, user_org_ids
from app.api.engine_routes import require_idle, workflow_file_activity
from app.api.mappers import to_workflow_finding_public
from app.api.router import Role, RoleRouter
from app.models import (
    Category,
    FindingCategoryStat,
    FindingUpdate,
    RepoCategoryStat,
    RepoFindingStats,
    Repository,
    Rule,
    Severity,
    TargetAction,
    WorkflowFile,
    WorkflowFinding,
    WorkflowFindingPublic,
    WorkflowFindingStatsPublic,
    WorkflowFix,
    WorkflowScan,
)
from app.services.scoring import (
    compute_avg_scores_batch,
    compute_category_scores,
    score_to_grade,
    severity_penalty_case,
)
from app.services.state_machines import REJECTED_STATUSES
from app.services.workflow_fixes import is_from_latest_scan

router = RoleRouter()


def _visible_findings(
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID | None,
    branch: str | None,
    latest_only: bool,
) -> Any:
    """The findings the caller may see, narrowed the way both reads narrow them.

    Findings belong to a per-branch ``WorkflowFile``, so a repository read
    without an explicit branch shows the default branch — feature-branch
    findings appear only when asked for. ``latest_only`` keeps each file's
    latest completed scan, regardless of repository scoping, so org-wide reads
    (the dashboard) do not count rows left over from earlier scans.

    ``WorkflowScan`` is always joined: tenant scoping, the repository filter and
    the per-repository breakdown all read it, and the foreign key is non-null.
    """
    query = select(WorkflowFinding).join(
        WorkflowScan, col(WorkflowFinding.analysis_id) == col(WorkflowScan.id)
    )
    if not current_user.is_superuser:
        query = query.where(
            col(WorkflowScan.repo_id).in_(
                select(Repository.id).where(
                    col(Repository.org_id).in_(user_org_ids(session, current_user))
                )
            )
        )
    if repo_id is not None:
        query = query.where(WorkflowScan.repo_id == repo_id)
        if branch is None:
            repo = session.get(Repository, repo_id)
            branch = repo.default_branch if repo else None
    if branch:
        query = query.join(
            WorkflowFile,
            col(WorkflowFinding.workflow_file_id) == col(WorkflowFile.id),
        ).where(WorkflowFile.branch == branch)
    if latest_only:
        query = query.where(is_from_latest_scan())
    return query


@router.get("/findings", role=Role.user, response_model=list[WorkflowFindingPublic])
def list_findings(
    session: SessionDep,
    current_user: CurrentUser,
    scan_id: uuid.UUID | None = None,
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
) -> list[WorkflowFindingPublic]:
    query = _visible_findings(session, current_user, repo_id, branch, latest_only)
    if not include_resolved:
        query = query.where(col(WorkflowFinding.resolved_at).is_(None))
    if not include_ignored:
        query = query.where(col(WorkflowFinding.ignored_at).is_(None))
    if scan_id:
        query = query.where(WorkflowFinding.analysis_id == scan_id)
    if unfixed:
        active_fix_ids = select(WorkflowFix.id).where(
            col(WorkflowFix.status).not_in(REJECTED_STATUSES)
        )
        query = query.where(
            col(WorkflowFinding.fix_id).is_(None)
            | ~col(WorkflowFinding.fix_id).in_(active_fix_ids)
        )
    if category:
        query = query.where(WorkflowFinding.category == category)
    if severity:
        query = query.where(WorkflowFinding.severity == severity)
    severity_rank = case(
        (col(WorkflowFinding.severity) == Severity.critical, 0),
        (col(WorkflowFinding.severity) == Severity.high, 1),
        (col(WorkflowFinding.severity) == Severity.medium, 2),
        (col(WorkflowFinding.severity) == Severity.low, 3),
        (col(WorkflowFinding.severity) == Severity.info, 4),
        else_=99,
    )
    query = (
        query.order_by(severity_rank, col(WorkflowFinding.created_at).desc())
        .offset(skip)
        .limit(limit)
    )
    return [to_workflow_finding_public(issue) for issue in session.exec(query).all()]


@router.get(
    "/findings/stats", role=Role.user, response_model=WorkflowFindingStatsPublic
)
def get_finding_stats(
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID | None = None,
    branch: str | None = None,
    latest_only: bool = True,
) -> WorkflowFindingStatsPublic:
    """Exact open/resolved issue counts by category, aggregated in SQL.

    Powers the dashboard's stat cards and category health breakdown without
    the pagination cap a plain ``list_issues`` fetch would hit on a large
    org — every matching row is summed server-side, never materialized into
    a capped page of ``WorkflowFindingPublic`` objects.
    """
    query = _visible_findings(
        session, current_user, repo_id, branch, latest_only
    ).where(col(WorkflowFinding.ignored_at).is_(None))

    is_open = col(WorkflowFinding.resolved_at).is_(None)
    is_critical = WorkflowFinding.severity == Severity.critical
    grouped = query.with_only_columns(
        WorkflowFinding.category,
        func.sum(case((is_open, 1), else_=0)).label("open"),
        func.sum(case((~is_open, 1), else_=0)).label("resolved"),
        func.sum(case((is_open & is_critical, 1), else_=0)).label("critical_open"),
    ).group_by(WorkflowFinding.category)

    # session.exec() would scalarize this to just the first column: the
    # original select(WorkflowFinding) statement stays a sqlmodel SelectOfScalar even
    # after with_only_columns() swaps in the aggregate columns. session.execute()
    # (the underlying SQLAlchemy call) returns full Row tuples instead.
    by_category = [
        FindingCategoryStat(
            category=row.category,
            open=row.open or 0,
            resolved=row.resolved or 0,
            critical_open=row.critical_open or 0,
        )
        for row in session.execute(grouped).all()
    ]

    # Per-repo breakdown for the dashboard's category health star diagram.
    # Only meaningful when not already scoped to a single repo; joins Rule for
    # its severity_weight.
    by_repo: list[RepoFindingStats] = []
    if repo_id is None:
        repo_query = query.join(Rule, col(WorkflowFinding.rule_id) == col(Rule.id))
        repo_grouped = repo_query.with_only_columns(
            WorkflowScan.repo_id,
            WorkflowFinding.category,
            func.sum(case((is_open, 1), else_=0)).label("open"),
            func.sum(case((is_open & is_critical, 1), else_=0)).label("critical_open"),
            func.sum(
                case(
                    (
                        is_open,
                        severity_penalty_case(col(WorkflowFinding.severity))
                        * Rule.severity_weight,
                    ),
                    else_=0.0,
                )
            ).label("weighted_penalty"),
        ).group_by(WorkflowScan.repo_id, WorkflowFinding.category)
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
                RepoFindingStats(
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

    return WorkflowFindingStatsPublic(
        total_open=sum(r.open for r in by_category),
        total_resolved=sum(r.resolved for r in by_category),
        critical_open=sum(r.critical_open for r in by_category),
        by_category=by_category,
        by_repo=by_repo,
    )


@router.get(
    "/findings/{finding_id}",
    role=Role.org_member,
    response_model=WorkflowFindingPublic,
)
def get_finding(
    finding_id: uuid.UUID,
    session: SessionDep,
) -> WorkflowFindingPublic:
    return to_workflow_finding_public(get_or_404(session, WorkflowFinding, finding_id))


@router.patch(
    "/findings/{finding_id}",
    role=Role.org_admin,
    response_model=WorkflowFindingPublic,
)
def update_finding(
    finding_id: uuid.UUID,
    body: FindingUpdate,
    session: SessionDep,
) -> WorkflowFindingPublic:
    """Mute (``ignored: true``) or un-mute a violation.

    Muting sets ``ignored_at``; the DB trigger recomputes ``status`` to
    ``ignored``, which takes precedence over resolve/fix state and drops the
    issue out of the default (active) issue and fix queries. It is idempotent on
    an already-ignored issue and a 409 on a resolved one, as on every other
    engine (``FindingMachine.ignore`` is legal only from ``open`` and
    ``fix_in_progress``). Un-muting is idempotent in every state. The PR-comment
    ``/greensecops ignore`` path writes the column directly and is deliberately
    untouched: a bulk fingerprint mute is not a click on a button that should
    have been grey.
    """
    issue = get_or_404(session, WorkflowFinding, finding_id)
    if body.ignored is None or body.ignored == (issue.ignored_at is not None):
        return to_workflow_finding_public(issue)
    wf_file = get_or_404(session, WorkflowFile, issue.workflow_file_id)
    require_idle(
        workflow_file_activity(session, wf_file), TargetAction.ignore, "workflow file"
    )
    if body.ignored and issue.resolved_at is not None:
        raise HTTPException(
            status_code=409,
            detail="A workflow finding that is resolved cannot be ignored",
        )
    issue.ignored_at = datetime.now(timezone.utc) if body.ignored else None
    session.add(issue)
    session.commit()
    session.refresh(issue)
    return to_workflow_finding_public(issue)
