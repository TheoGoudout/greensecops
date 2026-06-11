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


def compute_score(
    violations: list[tuple[str, float]],  # list of (severity_value, rule_weight)
) -> float:
    """Compute 0–100 score. Each violation penalises based on severity * rule_weight."""
    penalty = sum(
        _SEVERITY_PENALTY.get(sev, 5.0) * weight for sev, weight in violations
    )
    return max(0.0, 100.0 - penalty)


def score_to_grade(score: float) -> str:
    for threshold, grade in _GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"
