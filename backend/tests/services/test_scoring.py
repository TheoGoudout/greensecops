from app.services.scoring import compute_score, score_to_grade


# ─── score_to_grade (unchanged) ────────────────────────────────────────────


def test_grade_a_plus_plus_plus() -> None:
    assert score_to_grade(100.0) == "A+++"
    assert score_to_grade(99.0) == "A+++"


def test_grade_f() -> None:
    assert score_to_grade(0.0) == "F"
    assert score_to_grade(39.9) == "F"


def test_grade_b() -> None:
    assert score_to_grade(75.0) == "B"


# ─── compute_score ──────────────────────────────────────────────────────────


def test_perfect_score_no_violations() -> None:
    assert compute_score([], {}) == 100.0


def test_perfect_score_jobs_with_no_violations() -> None:
    assert compute_score([], {"build": [], "test": [], "deploy": []}) == 100.0


def test_workflow_level_violation_only() -> None:
    score = compute_score([("critical", 1.0)], {})
    assert score == 80.0  # 100 - 20*1.0


def test_single_job_with_violation() -> None:
    score = compute_score([], {"build": [("high", 1.0)]})
    assert score == 90.0  # 100 - 10*1.0


def test_job_count_does_not_inflate_penalty() -> None:
    one_job = compute_score([], {"build": [("high", 1.0)]})
    two_jobs = compute_score(
        [],
        {
            "build": [("high", 1.0)],
            "test": [("high", 1.0)],
        },
    )
    assert one_job == two_jobs  # Both 90.0


def test_mixed_job_quality() -> None:
    score = compute_score(
        [],
        {
            "good_job": [],
            "bad_job": [("high", 1.0)],
        },
    )
    assert score == 95.0  # (100 + 90) / 2


def test_workflow_penalty_stacks_on_job_mean() -> None:
    score = compute_score(
        [("critical", 1.0)],  # workflow penalty = 20
        {"build": [("high", 1.0)]},  # job score = 90
    )
    assert score == 70.0  # 90 - 20


def test_score_clamped_at_zero() -> None:
    violations = [("critical", 1.0)] * 10
    score = compute_score(violations, {})
    assert score == 0.0


def test_score_clamped_at_zero_via_jobs() -> None:
    score = compute_score(
        [],
        {"overloaded": [("critical", 1.0)] * 10},
    )
    assert score == 0.0


def test_score_decreases_with_violations() -> None:
    no_issues = compute_score([], {})
    one_high = compute_score([], {"build": [("high", 1.0)]})
    assert no_issues > one_high
