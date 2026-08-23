import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import Case, case
from sqlalchemy.orm import Mapped
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Session, col, select

from app.models import (
    Analysis,
    AnalysisStatus,
    Category,
    Repository,
    Severity,
    WorkflowFile,
)

_SEVERITY_PENALTY: dict[str, float] = {
    Severity.critical: 20.0,
    Severity.high: 10.0,
    Severity.medium: 5.0,
    Severity.low: 2.0,
    Severity.info: 0.5,
}

_GRADE_THRESHOLDS: list[tuple[float, str]] = [
    (98.0, "A+++"),
    (95.0, "A++"),
    (90.0, "A+"),
    (85.0, "A"),
    (70.0, "B"),
    (55.0, "C"),
    (40.0, "D"),
    (0.0, "F"),
]

# The grade rungs, best first. Public because callers that *count* grades
# rather than compute them (the dashboard overview's grade distribution) need
# to zero-fill the rungs nothing landed on, and deriving the ladder from a
# private constant in two places is how the two drift apart.
GRADE_LADDER: tuple[str, ...] = tuple(grade for _, grade in _GRADE_THRESHOLDS)


def _compute_penalty(
    violations: list[tuple[str, float]],
) -> float:
    return sum(_SEVERITY_PENALTY.get(sev, 5.0) * weight for sev, weight in violations)


def compute_score(
    target_violations: list[tuple[str, float]],
    group_violations: dict[str, list[tuple[str, float]]],
) -> float:
    """Compute a 0-100 score, normalised across whatever the groups are.

    Each group is scored independently (100 minus its penalties, clamped to 0)
    and the result is their mean, minus any penalties that apply to the target
    as a whole rather than to one group.

    The parameters used to be named ``workflow_violations`` and
    ``job_violations``, after the first engine to use this. Every engine scores
    through it now, and the names stopped describing what callers pass: the
    Docker engine groups by *file*, and needed a paragraph of comment at its own
    call site explaining that files take the place jobs occupy here. A group is
    a job for the CI engine, a file for Docker; Terraform has no groups and
    passes ``{}``, which scores the target's violations against a clean 100.
    """
    if group_violations:
        group_scores = [
            max(0.0, 100.0 - _compute_penalty(viols))
            for viols in group_violations.values()
        ]
        avg_group_score = sum(group_scores) / len(group_scores)
    else:
        avg_group_score = 100.0

    return max(0.0, avg_group_score - _compute_penalty(target_violations))


def score_to_grade(score: float) -> str:
    for threshold, grade in _GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def average_latest_scores(analyses: list[Any]) -> tuple[float | None, int]:
    """Average the score of the latest analysis per workflow file.

    ``analyses`` must be ordered by (workflow_file_id, created_at desc) so the
    first row seen for each workflow file is its most recent. Returns
    (avg_score, workflow_file_count); avg_score is None when there are no scores.
    Shared by the repository- and badge-grade endpoints to keep one definition
    of "a repo's grade".
    """
    seen: set[Any] = set()
    scores: list[float] = []
    for a in analyses:
        if a.workflow_file_id in seen:
            continue
        seen.add(a.workflow_file_id)
        if a.score is not None:
            scores.append(a.score)
    if not scores:
        return None, 0
    return sum(scores) / len(scores), len(scores)


def compute_avg_scores_batch(
    session: Session, repo_ids: list[uuid.UUID]
) -> dict[uuid.UUID, float | None]:
    """Batch avg_score per repo from the latest analysis per workflow file.

    Scoped to default-branch, non-deleted workflow files so feature-branch
    analyses don't skew the score, mirroring ``average_latest_scores``.
    ``None`` for a repo means it has no scored analyses; callers decide how
    to represent that (e.g. grade "N/A" vs "-"). Shared by the repositories
    batch-grade endpoint and the issue-stats per-category breakdown so both
    use one definition of "a repo's average score".
    """
    if not repo_ids:
        return {}

    analyses = session.exec(
        select(Analysis)
        .join(WorkflowFile, Analysis.workflow_file_id == WorkflowFile.id)  # type: ignore[arg-type]
        .join(Repository, Analysis.repo_id == Repository.id)  # type: ignore[arg-type]
        .where(Analysis.repo_id.in_(repo_ids))  # type: ignore[attr-defined]
        .where(WorkflowFile.branch == Repository.default_branch)
        .where(col(WorkflowFile.deleted_at).is_(None))
        .where(Analysis.status == AnalysisStatus.completed)
        .where(Analysis.score.isnot(None))  # type: ignore[union-attr]
        .order_by(col(Analysis.workflow_file_id), col(Analysis.created_at).desc())
    ).all()

    seen: set[uuid.UUID] = set()
    scores_by_repo: dict[uuid.UUID, list[float]] = defaultdict(list)
    for a in analyses:
        if a.workflow_file_id is not None and a.workflow_file_id not in seen:
            seen.add(a.workflow_file_id)
            if a.score is not None:
                scores_by_repo[a.repo_id].append(a.score)

    result: dict[uuid.UUID, float | None] = {}
    for repo_id in repo_ids:
        scores = scores_by_repo.get(repo_id, [])
        result[repo_id] = sum(scores) / len(scores) if scores else None
    return result


def severity_penalty_case(severity_col: ColumnElement[Any] | Mapped[Any]) -> Case[Any]:
    """SQL ``CASE`` mapping a severity column to its penalty weight.

    Mirrors ``_SEVERITY_PENALTY`` for use inside aggregate queries (e.g.
    summing weighted issue penalty per category without fetching rows).

    ``Mapped`` is in the union because callers reach the column through
    SQLModel's ``col()``, which is typed to return it — a model attribute is a
    column expression at runtime, but only ``col()`` says so to the checker.
    """
    return case(
        *[(severity_col == sev, penalty) for sev, penalty in _SEVERITY_PENALTY.items()],
        else_=5.0,
    )


def compute_category_scores(
    repo_avg_score: float, penalties: dict[Category, float]
) -> dict[Category, tuple[float, str]]:
    """Split a repo's overall score into per-category scores/grades.

    Each category's score deviates from ``repo_avg_score`` by how far its
    weighted issue penalty sits from the mean penalty across *all*
    categories, so the categories' scores average out to exactly
    ``repo_avg_score`` (pre-clamp — a category with a very large penalty
    share can still clamp at 0, which then breaks the exact-average
    property, but only for pathologically skewed repos).

    ``penalties`` must have an entry for every ``Category`` (0.0 where
    there are no open issues) so the mean is computed over all axes, not just
    the categories that happen to have issues.
    """
    mean_penalty = sum(penalties.values()) / len(Category)
    result: dict[Category, tuple[float, str]] = {}
    for category in Category:
        deviation = penalties[category] - mean_penalty
        score = max(0.0, min(100.0, repo_avg_score - deviation))
        result[category] = (score, score_to_grade(score))
    return result
