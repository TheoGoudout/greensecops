from typing import Any

from app.models import IssueSeverity

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
