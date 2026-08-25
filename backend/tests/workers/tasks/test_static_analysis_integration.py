"""Integration tests for static_analysis against real-world workflow files.

Adding a new workflow fixture requires two files in tests/fixtures/workflows/:
  - {name}.yml         — the workflow YAML (drop in from any public repo)
  - {name}.expected.json — violations + assertions (see existing files for format)

The parametrized test below auto-discovers every matched pair and runs the full
analysis pipeline against it. No test code changes needed.


Workflows are fetched from public repos (encode/httpx, celery/celery, redis/redis-py)
and stored in tests/fixtures/workflows/. OPA calls are mocked at _evaluate with
violations that accurately reflect what each rule would detect, so the tests validate
the full pipeline: line-number enrichment, WorkflowFinding creation, score degradation, and
content-hash deduplication.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.models import (
    Category,
    Organization,
    Repository,
    Rule,
    ScanStatus,
    UserTier,
    WorkflowFile,
    WorkflowScan,
)
from app.services.opa.evaluator import _attach_positions
from app.services.workflow_parser import parse_workflow_yaml
from app.workers.tasks.static_analysis import _run_static_analysis_impl

# ─── Helpers ─────────────────────────────────────────────────────────────────

_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "workflows"


def _load(name: str) -> str:
    return (_FIXTURES / name).read_text()


@dataclass
class _Violation:
    rule_slug: str
    severity: str
    category: str
    message: str
    job: str | None = None
    step: str | None = None
    step_index: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    context: str | None = None
    discriminator: str | None = None


def _make_wf(db: Session, repo: Repository, content: str, path: str) -> WorkflowFile:
    wf = WorkflowFile(
        repo_id=repo.id,
        path=path,
        content_hash=uuid.uuid4().hex,
        raw_content=content,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    o = Organization(name=f"sa-integ-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


@pytest.fixture()
def repo(db: Session, org: Organization) -> Repository:
    r = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"sa-integ/repo-{uuid.uuid4().hex[:8]}",
        installation_id=30001,
        default_branch="main",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@pytest.fixture()
def unpinned_rule(db: Session) -> Rule:
    rule = db.exec(select(Rule).where(Rule.slug == "unpinned_actions")).first()
    assert rule is not None, "unpinned_actions rule not seeded — run init_db"
    return rule


@pytest.fixture()
def timeout_rule(db: Session) -> Rule:
    rule = db.exec(select(Rule).where(Rule.slug == "missing_timeout")).first()
    assert rule is not None, "missing_timeout rule not seeded — run init_db"
    return rule


# ═══════════════════════════════════════════════════════════════════════════════
# Line attribution against real workflows — no DB, no Celery
# ═══════════════════════════════════════════════════════════════════════════════


def _locate(violations: list[_Violation], content: str) -> None:
    """Resolve each violation's line the way evaluate_workflow does."""
    parsed = parse_workflow_yaml(content)
    assert parsed is not None
    for violation in violations:
        _attach_positions(violation, parsed)


def _unpinned(job: str, step: str, index: int) -> _Violation:
    return _Violation(
        "unpinned_actions",
        "high",
        "reliability",
        "msg",
        job=job,
        step=step,
        step_index=index,
    )


def test_httpx_step_resolves_to_its_own_line() -> None:
    # httpx_test_suite.yml line 19 is `- uses: "actions/checkout@v4"`.
    content = _load("httpx_test_suite.yml")
    v = _unpinned("tests", "actions/checkout@v4", 0)
    _locate([v], content)
    assert v.line_start == 19


def test_httpx_steps_resolve_in_file_order() -> None:
    content = _load("httpx_test_suite.yml")
    checkout = _unpinned("tests", "actions/checkout@v4", 0)
    setup_py = _unpinned("tests", "actions/setup-python@v6", 1)
    _locate([checkout, setup_py], content)
    assert checkout.line_start == 19
    assert setup_py.line_start == 20


def test_httpx_run_step_gets_a_line_too() -> None:
    """A `run:` step is resolved like any other.

    The previous implementation matched steps by their `uses` value, so a
    `run:` step had no `uses` to match and every finding on one — the whole of
    curl_pipe_shell_in_run, script_injection_expression,
    deprecated_workflow_commands — was reported with no line at all.
    """
    content = _load("httpx_test_suite.yml")
    # Index 3 is `- name: "Install dependencies"`, a run step.
    v = _Violation(
        "deprecated_workflow_commands",
        "low",
        "maintainability",
        "msg",
        job="tests",
        step_index=3,
    )
    _locate([v], content)
    assert v.line_start is not None
    assert v.line_start > 20


def test_httpx_job_level_violation_resolves_to_the_job_key() -> None:
    content = _load("httpx_test_suite.yml")
    v = _Violation("missing_timeout", "high", "reliability", "No timeout", job="tests")
    _locate([v], content)
    # `tests:` is line 10 in the fixture.
    assert v.line_start == 10


def test_celery_every_violation_in_a_job_gets_a_line() -> None:
    content = _load("celery_ci.yml")
    violations: list[_Violation] = [
        _unpinned("Unit", "actions/checkout@v7", 0),
        _unpinned("Unit", "actions/setup-python@v6", 1),
        _unpinned("Unit", "codecov/codecov-action@v7", 5),
        _Violation("missing_timeout", "high", "reliability", "No timeout", job="Unit"),
    ]
    _locate(violations, content)
    for v in violations:
        assert v.line_start is not None and v.line_start > 0, (
            f"Expected line_start for {v.rule_slug}/{v.step}"
        )


def test_two_steps_using_one_action_get_distinct_lines() -> None:
    """Keyed on the index, not the action name.

    Matching on `uses` broke on the first hit, so every violation on a repeated
    action reported the first occurrence's line.
    """
    content = _load("celery_ci.yml")
    first = _unpinned("Unit", "actions/checkout@v7", 0)
    second = _unpinned("Integration-tests", "actions/checkout@v7", 0)
    _locate([first, second], content)
    assert first.line_start is not None and second.line_start is not None
    assert first.line_start != second.line_start


def test_redis_py_each_job_resolves_to_a_distinct_line() -> None:
    content = _load("redis_py_integration.yml")
    violations = [
        _Violation(
            "missing_timeout",
            "high",
            "reliability",
            f"Job '{job}' has no timeout",
            job=job,
        )
        for job in (
            "dependency-audit",
            "lint",
            "build-and-test-package",
            "install-package-from-commit",
        )
    ]
    _locate(violations, content)
    starts = [v.line_start for v in violations]
    assert all(s is not None and s > 0 for s in starts)
    assert len(set(starts)) == len(starts), "each job must be on a distinct line"


def test_unknown_job_leaves_the_line_unset() -> None:
    content = _load("httpx_test_suite.yml")
    v = _Violation(
        "missing_timeout", "high", "reliability", "msg", job="nonexistent-job"
    )
    _locate([v], content)
    assert v.line_start is None


def test_out_of_range_step_index_falls_back_to_the_job() -> None:
    # Better an approximate line on the right job than none at all.
    content = _load("httpx_test_suite.yml")
    v = _unpinned("tests", "nonexistent/action@v99", 99)
    _locate([v], content)
    assert v.line_start == 10


# ═══════════════════════════════════════════════════════════════════════════════
# Full pipeline tests — DB + mocked _evaluate
# ═══════════════════════════════════════════════════════════════════════════════


def test_httpx_analysis_creates_three_issues(db: Session, repo: Repository) -> None:
    """httpx workflow: 2 unpinned actions + 1 missing timeout → 3 issues, grade degraded."""
    unique = uuid.uuid4().hex
    content = f"# test-{unique}\n" + _load("httpx_test_suite.yml")
    wf = _make_wf(db, repo, content, f".github/workflows/httpx-{unique}.yml")

    violations = [
        _Violation(
            "unpinned_actions",
            "high",
            "reliability",
            "actions/checkout@v4 uses a mutable ref",
            job="tests",
            step="actions/checkout@v4",
        ),
        _Violation(
            "unpinned_actions",
            "high",
            "reliability",
            "actions/setup-python@v6 uses a mutable ref",
            job="tests",
            step="actions/setup-python@v6",
        ),
        _Violation(
            "missing_timeout",
            "high",
            "reliability",
            "Job 'tests' has no timeout-minutes configured.",
            job="tests",
        ),
    ]

    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files", return_value=[wf]
        ),
        patch("app.workers.tasks.static_analysis._evaluate", return_value=violations),
    ):
        result = _run_static_analysis_impl(str(repo.id))

    assert result["status"] == "done"
    results_str = result["results"]
    assert "completed" in results_str
    assert "'issues': 3" in results_str or '"issues": 3' in results_str

    analysis = db.exec(
        select(WorkflowScan)
        .where(WorkflowScan.repo_id == repo.id)
        .where(WorkflowScan.status == ScanStatus.completed)
        .order_by(WorkflowScan.created_at.desc())  # type: ignore[arg-type]
    ).first()
    assert analysis is not None
    assert analysis.grade != "A+++"


def test_httpx_analysis_issues_have_positive_line_numbers(
    db: Session, repo: Repository
) -> None:
    """All issues created from the httpx workflow have line_start > 0."""
    from app.models import WorkflowFinding

    unique = uuid.uuid4().hex
    content = f"# test-{unique}\n" + _load("httpx_test_suite.yml")
    wf = _make_wf(db, repo, content, f".github/workflows/httpx-lines-{unique}.yml")

    violations = [
        _Violation(
            "unpinned_actions",
            "high",
            "reliability",
            "Mutable ref",
            job="tests",
            step="actions/checkout@v4",
        ),
        _Violation("missing_timeout", "high", "reliability", "No timeout", job="tests"),
    ]
    _locate(violations, content)

    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files", return_value=[wf]
        ),
        patch("app.workers.tasks.static_analysis._evaluate", return_value=violations),
    ):
        _run_static_analysis_impl(str(repo.id))

    analysis = db.exec(
        select(WorkflowScan)
        .where(WorkflowScan.repo_id == repo.id)
        .where(WorkflowScan.status == ScanStatus.completed)
        .order_by(WorkflowScan.created_at.desc())  # type: ignore[arg-type]
    ).first()
    assert analysis is not None

    issues = db.exec(
        select(WorkflowFinding).where(WorkflowFinding.analysis_id == analysis.id)
    ).all()
    assert len(issues) == 2
    assert all(i.line_start is not None and i.line_start > 0 for i in issues)


def test_celery_analysis_creates_four_issues_across_categories(
    db: Session, repo: Repository
) -> None:
    """celery CI: 3 unpinned + 1 missing timeout → 4 issues, all reliability category."""
    from app.models import WorkflowFinding

    unique = uuid.uuid4().hex
    content = f"# test-{unique}\n" + _load("celery_ci.yml")
    wf = _make_wf(db, repo, content, f".github/workflows/celery-{unique}.yml")

    violations = [
        _Violation(
            "unpinned_actions",
            "high",
            "reliability",
            "actions/checkout@v7 uses a mutable ref",
            job="Unit",
            step="actions/checkout@v7",
        ),
        _Violation(
            "unpinned_actions",
            "high",
            "reliability",
            "actions/setup-python@v6 uses a mutable ref",
            job="Unit",
            step="actions/setup-python@v6",
        ),
        _Violation(
            "unpinned_actions",
            "high",
            "reliability",
            "codecov/codecov-action@v7 uses a mutable ref",
            job="Unit",
            step="codecov/codecov-action@v7",
        ),
        _Violation(
            "missing_timeout",
            "high",
            "reliability",
            "Job 'Unit' has no timeout-minutes configured.",
            job="Unit",
        ),
    ]

    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files", return_value=[wf]
        ),
        patch("app.workers.tasks.static_analysis._evaluate", return_value=violations),
    ):
        result = _run_static_analysis_impl(str(repo.id))

    results_str = result["results"]
    assert "'issues': 4" in results_str or '"issues": 4' in results_str

    analysis = db.exec(
        select(WorkflowScan)
        .where(WorkflowScan.repo_id == repo.id)
        .where(WorkflowScan.status == ScanStatus.completed)
        .order_by(WorkflowScan.created_at.desc())  # type: ignore[arg-type]
    ).first()
    issues = db.exec(
        select(WorkflowFinding).where(WorkflowFinding.analysis_id == analysis.id)
    ).all()
    assert all(i.category == Category.reliability for i in issues)
    assert analysis.grade != "A+++"


def test_redis_py_analysis_creates_issues_per_job(
    db: Session, repo: Repository
) -> None:
    """redis-py: 4 jobs missing timeout + 1 unpinned → 5 issues; timeout issues on correct jobs."""
    from app.models import WorkflowFinding

    unique = uuid.uuid4().hex
    content = f"# test-{unique}\n" + _load("redis_py_integration.yml")
    wf = _make_wf(db, repo, content, f".github/workflows/redis-py-{unique}.yml")

    jobs_without_timeout = [
        "dependency-audit",
        "lint",
        "build-and-test-package",
        "install-package-from-commit",
    ]
    violations = [
        _Violation(
            "missing_timeout",
            "high",
            "reliability",
            f"Job '{j}' has no timeout-minutes configured.",
            job=j,
        )
        for j in jobs_without_timeout
    ] + [
        _Violation(
            "unpinned_actions",
            "high",
            "reliability",
            "actions/checkout@v7 uses a mutable ref",
            job="lint",
            step="actions/checkout@v7",
        ),
    ]
    _locate(violations, content)

    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files", return_value=[wf]
        ),
        patch("app.workers.tasks.static_analysis._evaluate", return_value=violations),
    ):
        _run_static_analysis_impl(str(repo.id))

    analysis = db.exec(
        select(WorkflowScan)
        .where(WorkflowScan.repo_id == repo.id)
        .where(WorkflowScan.status == ScanStatus.completed)
        .order_by(WorkflowScan.created_at.desc())  # type: ignore[arg-type]
    ).first()
    assert analysis is not None

    issues = db.exec(
        select(WorkflowFinding).where(WorkflowFinding.analysis_id == analysis.id)
    ).all()
    assert len(issues) == 5

    timeout_issues = [
        i for i in issues if i.job in jobs_without_timeout and i.step is None
    ]
    assert len(timeout_issues) == 4
    assert all(i.line_start is not None and i.line_start > 0 for i in timeout_issues)


def test_same_content_second_analysis_is_skipped(db: Session, repo: Repository) -> None:
    """Re-analysing identical content produces a skipped_duplicate analysis without re-evaluating."""
    unique = uuid.uuid4().hex
    content = f"# dedup-{unique}\n" + _load("httpx_test_suite.yml")
    wf = _make_wf(db, repo, content, f".github/workflows/httpx-dedup-{unique}.yml")

    violations = [
        _Violation("missing_timeout", "high", "reliability", "No timeout", job="tests"),
    ]

    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files", return_value=[wf]
        ),
        patch("app.workers.tasks.static_analysis._evaluate", return_value=violations),
    ):
        first = _run_static_analysis_impl(str(repo.id))

    assert "completed" in first["results"]

    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files", return_value=[wf]
        ),
        patch(
            "app.workers.tasks.static_analysis._evaluate", return_value=violations
        ) as mock_eval,
    ):
        second = _run_static_analysis_impl(str(repo.id))

    assert "skipped_duplicate" in second["results"]
    mock_eval.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# Auto-discovered parametrized tests
#
# Drop a new pair into tests/fixtures/workflows/:
#   my_workflow.yml           — real workflow YAML
#   my_workflow.expected.json — {"violations": [...], "expected_issue_count": N, "grade_not": "A+++"}
#
# This test picks it up automatically. No code changes needed.
# ═══════════════════════════════════════════════════════════════════════════════

_SCENARIOS = sorted(
    p.stem
    for p in _FIXTURES.glob("*.yml")
    if (_FIXTURES / p.stem).with_suffix(".expected.json").exists()
)


def _load_scenario(name: str) -> tuple[str, list[_Violation], dict]:
    content = (_FIXTURES / f"{name}.yml").read_text()
    meta = json.loads((_FIXTURES / f"{name}.expected.json").read_text())
    violations = [_Violation(**v) for v in meta["violations"]]
    # `_evaluate` is mocked below, so line attribution — which now happens
    # inside evaluate_workflow rather than in the analysis task — has to be
    # applied here for the fixture to stand in for what OPA really returns.
    _locate(violations, content)
    return content, violations, meta


@pytest.mark.parametrize("scenario", _SCENARIOS)
def test_workflow_scenario(db: Session, repo: Repository, scenario: str) -> None:
    """Auto-discovered workflow scenario: full pipeline smoke test."""
    from app.models import WorkflowFinding

    content, violations, meta = _load_scenario(scenario)
    unique = uuid.uuid4().hex
    wf = _make_wf(
        db,
        repo,
        f"# {unique}\n" + content,
        f".github/workflows/{scenario}-{unique}.yml",
    )

    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files", return_value=[wf]
        ),
        patch("app.workers.tasks.static_analysis._evaluate", return_value=violations),
    ):
        result = _run_static_analysis_impl(str(repo.id))

    assert result["status"] == "done"
    assert "completed" in result["results"]

    analysis = db.exec(
        select(WorkflowScan)
        .where(WorkflowScan.repo_id == repo.id)
        .where(WorkflowScan.status == ScanStatus.completed)
        .order_by(WorkflowScan.created_at.desc())  # type: ignore[arg-type]
    ).first()
    assert analysis is not None

    issues = db.exec(
        select(WorkflowFinding).where(WorkflowFinding.analysis_id == analysis.id)
    ).all()
    assert len(issues) == meta["expected_issue_count"], (
        f"{scenario}: expected {meta['expected_issue_count']} issues, got {len(issues)}"
    )

    if grade_not := meta.get("grade_not"):
        assert analysis.grade != grade_not, (
            f"{scenario}: grade should not be {grade_not!r}"
        )

    issues_with_job = [i for i in issues if i.job is not None]
    assert all(
        i.line_start is not None and i.line_start > 0 for i in issues_with_job
    ), f"{scenario}: all job-scoped issues must have line_start > 0"
