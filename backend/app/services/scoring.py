import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import Case, case
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Session, col, select

from app.models import (
    Analysis,
    AnalysisStatus,
    IssueCategory,
    IssueSeverity,
    Repository,
    WorkflowFile,
)

_SEVERITY_PENALTY: dict[str, float] = {
    IssueSeverity.critical: 20.0,
    IssueSeverity.high: 10.0,
    IssueSeverity.medium: 5.0,
    IssueSeverity.low: 2.0,
    IssueSeverity.info: 0.5,
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


def _compute_penalty(
    violations: list[tuple[str, float]],
) -> float:
    return sum(_SEVERITY_PENALTY.get(sev, 5.0) * weight for sev, weight in violations)


def compute_score(
    workflow_violations: list[tuple[str, float]],
    job_violations: dict[str, list[tuple[str, float]]],
) -> float:
    """Compute 0-100 score normalised by number of jobs.

    Each job is scored independently (100 minus its penalties, clamped to 0).
    The workflow score is the mean of all job scores, minus workflow-level
    penalties.
    """
    if job_violations:
        job_scores = [
            max(0.0, 100.0 - _compute_penalty(viols))
            for viols in job_violations.values()
        ]
        avg_job_score = sum(job_scores) / len(job_scores)
    else:
        avg_job_score = 100.0

    wf_penalty = _compute_penalty(workflow_violations)
    return max(0.0, avg_job_score - wf_penalty)


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


def severity_penalty_case(severity_col: ColumnElement[Any]) -> Case[Any]:
    """SQL ``CASE`` mapping a severity column to its penalty weight.

    Mirrors ``_SEVERITY_PENALTY`` for use inside aggregate queries (e.g.
    summing weighted issue penalty per category without fetching rows).
    """
    return case(
        *[(severity_col == sev, penalty) for sev, penalty in _SEVERITY_PENALTY.items()],
        else_=5.0,
    )


def compute_category_scores(
    repo_avg_score: float, penalties: dict[IssueCategory, float]
) -> dict[IssueCategory, tuple[float, str]]:
    """Split a repo's overall score into per-category scores/grades.

    Each category's score deviates from ``repo_avg_score`` by how far its
    weighted issue penalty sits from the mean penalty across *all*
    categories, so the categories' scores average out to exactly
    ``repo_avg_score`` (pre-clamp — a category with a very large penalty
    share can still clamp at 0, which then breaks the exact-average
    property, but only for pathologically skewed repos).

    ``penalties`` must have an entry for every ``IssueCategory`` (0.0 where
    there are no open issues) so the mean is computed over all axes, not just
    the categories that happen to have issues.
    """
    mean_penalty = sum(penalties.values()) / len(IssueCategory)
    result: dict[IssueCategory, tuple[float, str]] = {}
    for category in IssueCategory:
        deviation = penalties[category] - mean_penalty
        score = max(0.0, min(100.0, repo_avg_score - deviation))
        result[category] = (score, score_to_grade(score))
    return result
