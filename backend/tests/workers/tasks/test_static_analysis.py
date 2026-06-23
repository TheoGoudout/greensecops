"""Unit tests for the static_analysis Celery task (extracted impl function)."""

import uuid
from dataclasses import dataclass
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.models import (
    Analysis,
    AnalysisStatus,
    IssueCategory,
    IssueSeverity,
    Organization,
    Repository,
    Rule,
    UserTier,
    WorkflowFile,
)
from app.workers.tasks.static_analysis import _run_static_analysis_impl

# ─── Violation stub ──────────────────────────────────────────────────────────


@dataclass
class FakeViolation:
    rule_slug: str
    severity: str
    category: str
    line_start: int
    line_end: int
    message: str
    context: str | None = None


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"static-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture()
def repo(db: Session, org: Organization) -> Repository:
    repository = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"staticowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=20001,
        default_branch="main",
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def workflow_file(db: Session, repo: Repository) -> WorkflowFile:
    unique = uuid.uuid4().hex
    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/static-test.yml",
        content_hash=unique,
        raw_content=f"# unique:{unique}\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps: []\n",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@pytest.fixture()
def seeded_rule(db: Session) -> Rule:
    """Return the first seeded rule, which we'll use for violation matching."""
    rule = db.exec(select(Rule)).first()
    assert rule is not None, "No seeded rules found — init_db may not have run"
    return rule


# ─── Tests ───────────────────────────────────────────────────────────────────


def test_repo_not_found_returns_error(db: Session) -> None:  # noqa: ARG001
    # Arrange — UUID that doesn't correspond to any repo
    missing_id = str(uuid.uuid4())

    # Act
    result = _run_static_analysis_impl(missing_id)

    # Assert
    assert result["status"] == "error"
    assert result["detail"] == "repository_not_found"


def test_no_workflow_files_returns_done_with_empty_results(
    db: Session, repo: Repository
) -> None:
    # Arrange — _fetch_workflow_files returns empty list
    with patch(
        "app.workers.tasks.static_analysis._fetch_workflow_files", return_value=[]
    ):
        result = _run_static_analysis_impl(str(repo.id))

    # Assert
    assert result["status"] == "done"
    assert result["repo_id"] == str(repo.id)
    # results string should represent empty list
    assert "[]" in str(result["results"])


def test_with_workflow_file_id_skips_fetch(
    db: Session, repo: Repository, workflow_file: WorkflowFile
) -> None:
    # Arrange — pass workflow_file_id directly; _fetch should NOT be called
    with (
        patch("app.workers.tasks.static_analysis._fetch_workflow_files") as mock_fetch,
        patch(
            "app.workers.tasks.static_analysis._evaluate",
            return_value=[],
        ) as _mock_eval,
    ):
        result = _run_static_analysis_impl(
            str(repo.id),
            workflow_file_id=str(workflow_file.id),
        )

    # Assert — fetch was never called
    mock_fetch.assert_not_called()
    assert result["status"] == "done"


def test_happy_path_no_violations_produces_A_grade(
    db: Session, repo: Repository, workflow_file: WorkflowFile
) -> None:
    # Arrange — _fetch returns the existing WorkflowFile; _evaluate returns no violations
    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files",
            return_value=[workflow_file],
        ),
        patch(
            "app.workers.tasks.static_analysis._evaluate",
            return_value=[],
        ),
    ):
        result = _run_static_analysis_impl(str(repo.id))

    # Assert
    assert result["status"] == "done"
    results_str = str(result["results"])
    assert "completed" in results_str
    # Score 100 → grade A+++
    assert "A+++" in results_str or "100" in results_str


def test_with_violations_creates_issues(
    db: Session, repo: Repository, workflow_file: WorkflowFile, seeded_rule: Rule
) -> None:
    # Arrange — one violation matching the seeded rule slug
    violation = FakeViolation(
        rule_slug=seeded_rule.slug,
        severity=seeded_rule.severity.value,
        category=seeded_rule.category.value,
        line_start=1,
        line_end=3,
        message="Test violation",
        context='{"step": "test"}',
    )

    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files",
            return_value=[workflow_file],
        ),
        patch(
            "app.workers.tasks.static_analysis._evaluate",
            return_value=[violation],
        ),
    ):
        result = _run_static_analysis_impl(str(repo.id))

    # Assert
    assert result["status"] == "done"
    results_str = str(result["results"])
    assert "completed" in results_str
    # 1 issue in the result
    assert "'issues': 1" in results_str or '"issues": 1' in results_str


def test_opa_failure_marks_analysis_failed(
    db: Session, repo: Repository, workflow_file: WorkflowFile
) -> None:
    # Arrange — _evaluate raises an exception
    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files",
            return_value=[workflow_file],
        ),
        patch(
            "app.workers.tasks.static_analysis._evaluate",
            side_effect=RuntimeError("OPA unavailable"),
        ),
    ):
        result = _run_static_analysis_impl(str(repo.id))

    # Assert — task returns done but inner result is failed
    assert result["status"] == "done"
    results_str = str(result["results"])
    assert "failed" in results_str

    # The analysis record should be in failed state
    analysis = db.exec(
        select(Analysis)
        .where(Analysis.repo_id == repo.id)
        .where(Analysis.status == AnalysisStatus.failed)
    ).first()
    assert analysis is not None
    assert "OPA unavailable" in (analysis.error_message or "")


def test_duplicate_detection_skips_second_run(
    db: Session, repo: Repository, workflow_file: WorkflowFile
) -> None:
    # Arrange — same content_hash content, _evaluate returns no violations both times
    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files",
            return_value=[workflow_file],
        ),
        patch(
            "app.workers.tasks.static_analysis._evaluate",
            return_value=[],
        ),
    ):
        # First run completes
        first_result = _run_static_analysis_impl(str(repo.id))

    # Second run — same workflow file (same content_hash) → duplicate
    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files",
            return_value=[workflow_file],
        ),
        patch(
            "app.workers.tasks.static_analysis._evaluate",
            return_value=[],
        ) as mock_eval,
    ):
        second_result = _run_static_analysis_impl(str(repo.id))

    # Assert — first succeeded, second was skipped (duplicate)
    assert first_result["status"] == "done"
    assert second_result["status"] == "done"
    second_results_str = str(second_result["results"])
    assert "skipped_duplicate" in second_results_str
    # _evaluate should NOT have been called for the duplicate
    mock_eval.assert_not_called()

    # A skipped Analysis record must exist with current timestamps and copied grade
    skipped = db.exec(
        select(Analysis)
        .where(Analysis.repo_id == repo.id)
        .where(Analysis.status == AnalysisStatus.skipped)
    ).first()
    assert skipped is not None
    assert skipped.grade == "A+++"
    assert skipped.completed_at is not None
    assert skipped.created_at is not None


@dataclass
class _FakeFile:
    """Non-WorkflowFile object with .content and .path (simulates GitHub API result)."""

    path: str
    content: str


def test_non_workflow_file_creates_new_record(db: Session, repo: Repository) -> None:
    # Arrange — _fetch returns a non-WorkflowFile object; no existing WorkflowFile in DB
    unique = uuid.uuid4().hex
    fake = _FakeFile(
        path=f".github/workflows/fetched-{unique}.yml",
        content=f"# {unique}\non: push\njobs: {{}}",
    )
    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files",
            return_value=[fake],
        ),
        patch("app.workers.tasks.static_analysis._evaluate", return_value=[]),
    ):
        result = _run_static_analysis_impl(str(repo.id))

    assert result["status"] == "done"
    assert "completed" in str(result["results"])


def test_non_workflow_file_updates_existing_record(
    db: Session, repo: Repository, workflow_file: WorkflowFile
) -> None:
    # Arrange — _fetch returns a non-WorkflowFile whose path matches an existing WorkflowFile
    unique = uuid.uuid4().hex
    fake = _FakeFile(
        path=workflow_file.path,
        content=f"# updated-{unique}\non: push\njobs: {{}}",
    )
    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files",
            return_value=[fake],
        ),
        patch("app.workers.tasks.static_analysis._evaluate", return_value=[]),
    ):
        result = _run_static_analysis_impl(str(repo.id))

    assert result["status"] == "done"
    assert "completed" in str(result["results"])


def test_violation_with_unknown_rule_slug_is_skipped(
    db: Session, repo: Repository, workflow_file: WorkflowFile
) -> None:
    # Arrange — violation with a slug that does not exist in seeded rules
    violation = FakeViolation(
        rule_slug="no-such-rule-slug",
        severity=IssueSeverity.low.value,
        category=IssueCategory.energy.value,
        line_start=1,
        line_end=1,
        message="ghost violation",
    )
    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files",
            return_value=[workflow_file],
        ),
        patch(
            "app.workers.tasks.static_analysis._evaluate",
            return_value=[violation],
        ),
    ):
        result = _run_static_analysis_impl(str(repo.id))

    # Analysis still completes — unknown slug is logged and skipped
    assert result["status"] == "done"
    assert "completed" in str(result["results"])


def test_completed_analysis_sets_latest_analysis_id(
    db: Session, repo: Repository, workflow_file: WorkflowFile
) -> None:
    # Arrange — first run
    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files",
            return_value=[workflow_file],
        ),
        patch("app.workers.tasks.static_analysis._evaluate", return_value=[]),
    ):
        _run_static_analysis_impl(str(repo.id))

    db.refresh(workflow_file)
    first_latest = workflow_file.latest_analysis_id
    assert first_latest is not None

    # Change content so the second run is not treated as a duplicate
    workflow_file.content_hash = uuid.uuid4().hex
    workflow_file.raw_content = f"# updated\n{workflow_file.raw_content}"
    db.add(workflow_file)
    db.commit()

    # Act — force second run
    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files",
            return_value=[workflow_file],
        ),
        patch("app.workers.tasks.static_analysis._evaluate", return_value=[]),
    ):
        _run_static_analysis_impl(str(repo.id), force=True)

    # Assert — latest_analysis_id advanced to the newer analysis
    db.refresh(workflow_file)
    assert workflow_file.latest_analysis_id is not None
    assert workflow_file.latest_analysis_id != first_latest
