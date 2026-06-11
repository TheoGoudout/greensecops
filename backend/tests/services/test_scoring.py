from app.services.scoring import compute_score, score_to_grade


def test_perfect_score() -> None:
    assert compute_score([]) == 100.0


def test_grade_a_plus_plus_plus() -> None:
    assert score_to_grade(100.0) == "A+++"
    assert score_to_grade(99.0) == "A+++"


def test_grade_f() -> None:
    assert score_to_grade(0.0) == "F"
    assert score_to_grade(39.9) == "F"


def test_grade_b() -> None:
    assert score_to_grade(75.0) == "B"


def test_score_with_critical_violation() -> None:
    score = compute_score([("critical", 1.0)])
    assert score == 80.0  # 100 - 20*1.0


def test_score_clamped_at_zero() -> None:
    violations = [("critical", 1.0)] * 10
    score = compute_score(violations)
    assert score == 0.0


def test_score_decreases_with_violations() -> None:
    no_issues = compute_score([])
    one_high = compute_score([("high", 1.0)])
    assert no_issues > one_high
