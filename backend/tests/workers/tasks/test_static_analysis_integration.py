"""Integration tests for static_analysis against real-world workflow files.

Adding a new workflow fixture requires two files in tests/fixtures/workflows/:
  - {name}.yml         — the workflow YAML (drop in from any public repo)
  - {name}.expected.json — violations + assertions (see existing files for format)

The parametrized test below auto-discovers every matched pair and runs the full
analysis pipeline against it. No test code changes needed.


Workflows are fetched from public repos (encode/httpx, celery/celery, redis/redis-py)
and stored in tests/fixtures/workflows/. OPA calls are mocked at _evaluate with
violations that accurately reflect what each rule would detect, so the tests validate
the full pipeline: line-number enrichment, Issue creation, score degradation, and
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
    Analysis,
    AnalysisStatus,
    IssueCategory,
    Organization,
    Repository,
    Rule,
    UserTier,
    WorkflowFile,
)
from app.workers.tasks.static_analysis import (
    _enrich_line_numbers,
    _run_static_analysis_impl,
)

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
# _enrich_line_numbers unit tests — no DB, no Celery
# ═══════════════════════════════════════════════════════════════════════════════


def test_enrich_httpx_checkout_step_gets_line_number() -> None:
    """checkout@v4 step in the httpx workflow resolves to a positive line number."""
    content = _load("httpx_test_suite.yml")
    v = _Violation(
        "unpinned_actions",
        "high",
        "reliability",
        "msg",
        job="tests",
        step="actions/checkout@v4",
    )
    _enrich_line_numbers([v], content)
    assert v.line_start is not None and v.line_start > 0


def test_enrich_httpx_setup_python_step_gets_line_number() -> None:
    content = _load("httpx_test_suite.yml")
    v = _Violation(
        "unpinned_actions",
        "high",
        "reliability",
        "msg",
        job="tests",
        step="actions/setup-python@v6",
    )
    _enrich_line_numbers([v], content)
    assert v.line_start is not None and v.line_start > 0


def test_enrich_httpx_checkout_line_before_setup_python_line() -> None:
    """Steps appear in file order — checkout line < setup-python line."""
    content = _load("httpx_test_suite.yml")
    checkout = _Violation(
        "unpinned_actions",
        "high",
        "reliability",
        "msg",
        job="tests",
        step="actions/checkout@v4",
    )
    setup_py = _Violation(
        "unpinned_actions",
        "high",
        "reliability",
        "msg",
        job="tests",
        step="actions/setup-python@v6",
    )
    _enrich_line_numbers([checkout, setup_py], content)
    assert checkout.line_start < setup_py.line_start


def test_enrich_httpx_job_level_timeout_violation_gets_line() -> None:
    """Job-level violation (step=None) resolves to the job key line."""
    content = _load("httpx_test_suite.yml")
    v = _Violation(
        "missing_timeout", "high", "reliability", "No timeout", job="tests", step=None
    )
    _enrich_line_numbers([v], content)
    assert v.line_start is not None and v.line_start > 0


def test_enrich_celery_all_unit_violations_get_line_numbers() -> None:
    """All violations in the celery Unit job (3 unpinned + 1 timeout) get line numbers."""
    content = _load("celery_ci.yml")
    violations = [
        _Violation(
            "unpinned_actions",
            "high",
            "reliability",
            "msg",
            job="Unit",
            step="actions/checkout@v7",
        ),
        _Violation(
            "unpinned_actions",
            "high",
            "reliability",
            "msg",
            job="Unit",
            step="actions/setup-python@v6",
        ),
        _Violation(
            "unpinned_actions",
            "high",
            "reliability",
            "msg",
            job="Unit",
            step="codecov/codecov-action@v7",
        ),
        _Violation(
            "missing_timeout",
            "high",
            "reliability",
            "No timeout",
            job="Unit",
            step=None,
        ),
    ]
    _enrich_line_numbers(violations, content)
    for v in violations:
        assert v.line_start is not None and v.line_start > 0, (
            f"Expected line_start for {v.rule_slug}/{v.step}"
        )


def test_enrich_redis_py_missing_timeout_per_job_distinct_lines() -> None:
    """Four redis-py jobs missing timeout each resolve to distinct line numbers."""
    content = _load("redis_py_integration.yml")
    job_names = [
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
            f"Job '{j}' has no timeout",
            job=j,
            step=None,
        )
        for j in job_names
    ]
    _enrich_line_numbers(violations, content)
    line_starts = [v.line_start for v in violations]
    assert all(ls is not None and ls > 0 for ls in line_starts)
    assert len(set(line_starts)) == len(line_starts), (
        "Each job must be on a distinct line"
    )


def test_enrich_unknown_job_leaves_line_start_unchanged() -> None:
    """Violation referencing a non-existent job is silently skipped."""
    content = _load("httpx_test_suite.yml")
    v = _Violation(
        "missing_timeout",
        "high",
        "reliability",
        "msg",
        job="nonexistent-job",
        step=None,
    )
    _enrich_line_numbers([v], content)
    assert v.line_start is None


def test_enrich_unknown_step_leaves_line_start_unchanged() -> None:
    """Violation referencing a step that does not exist in the job is skipped."""
    content = _load("httpx_test_suite.yml")
    v = _Violation(
        "unpinned_actions",
        "high",
        "reliability",
        "msg",
        job="tests",
        step="nonexistent/action@v99",
    )
    _enrich_line_numbers([v], content)
    assert v.line_start is None


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
        select(Analysis)
        .where(Analysis.repo_id == repo.id)
        .where(Analysis.status == AnalysisStatus.completed)
        .order_by(Analysis.created_at.desc())  # type: ignore[arg-type]
    ).first()
    assert analysis is not None
    assert analysis.grade != "A+++"


def test_httpx_analysis_issues_have_positive_line_numbers(
    db: Session, repo: Repository
) -> None:
    """All issues created from the httpx workflow have line_start > 0."""
    from app.models import Issue

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

    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files", return_value=[wf]
        ),
        patch("app.workers.tasks.static_analysis._evaluate", return_value=violations),
    ):
        _run_static_analysis_impl(str(repo.id))

    analysis = db.exec(
        select(Analysis)
        .where(Analysis.repo_id == repo.id)
        .where(Analysis.status == AnalysisStatus.completed)
        .order_by(Analysis.created_at.desc())  # type: ignore[arg-type]
    ).first()
    assert analysis is not None

    issues = db.exec(select(Issue).where(Issue.analysis_id == analysis.id)).all()
    assert len(issues) == 2
    assert all(i.line_start is not None and i.line_start > 0 for i in issues)


def test_celery_analysis_creates_four_issues_across_categories(
    db: Session, repo: Repository
) -> None:
    """celery CI: 3 unpinned + 1 missing timeout → 4 issues, all reliability category."""
    from app.models import Issue

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
        select(Analysis)
        .where(Analysis.repo_id == repo.id)
        .where(Analysis.status == AnalysisStatus.completed)
        .order_by(Analysis.created_at.desc())  # type: ignore[arg-type]
    ).first()
    issues = db.exec(select(Issue).where(Issue.analysis_id == analysis.id)).all()
    assert all(i.category == IssueCategory.reliability for i in issues)
    assert analysis.grade != "A+++"


def test_redis_py_analysis_creates_issues_per_job(
    db: Session, repo: Repository
) -> None:
    """redis-py: 4 jobs missing timeout + 1 unpinned → 5 issues; timeout issues on correct jobs."""
    from app.models import Issue

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

    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files", return_value=[wf]
        ),
        patch("app.workers.tasks.static_analysis._evaluate", return_value=violations),
    ):
        _run_static_analysis_impl(str(repo.id))

    analysis = db.exec(
        select(Analysis)
        .where(Analysis.repo_id == repo.id)
        .where(Analysis.status == AnalysisStatus.completed)
        .order_by(Analysis.created_at.desc())  # type: ignore[arg-type]
    ).first()
    assert analysis is not None

    issues = db.exec(select(Issue).where(Issue.analysis_id == analysis.id)).all()
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
    return content, violations, meta


@pytest.mark.parametrize("scenario", _SCENARIOS)
def test_workflow_scenario(db: Session, repo: Repository, scenario: str) -> None:
    """Auto-discovered workflow scenario: full pipeline smoke test."""
    from app.models import Issue

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
        select(Analysis)
        .where(Analysis.repo_id == repo.id)
        .where(Analysis.status == AnalysisStatus.completed)
        .order_by(Analysis.created_at.desc())  # type: ignore[arg-type]
    ).first()
    assert analysis is not None

    issues = db.exec(select(Issue).where(Issue.analysis_id == analysis.id)).all()
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
