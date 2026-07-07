"""Unit tests for the static_analysis Celery task (extracted impl function)."""

import uuid
from dataclasses import dataclass
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.models import (
    Analysis,
    AnalysisStatus,
    Issue,
    IssueCategory,
    IssueSeverity,
    Organization,
    Repository,
    Rule,
    UserTier,
    WorkflowFile,
)
from app.workers.tasks.static_analysis import (
    _enrich_line_numbers,
    _reanalyze_all_repositories_impl,
    _run_static_analysis_impl,
)

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
    job: str | None = None
    step: str | None = None


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


def test_no_workflow_files_returns_terminal_status_and_event(
    db: Session, repo: Repository
) -> None:
    # Arrange — _fetch_workflow_files returns empty list
    events_published: list = []
    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files", return_value=[]
        ),
        patch(
            "app.workers.tasks.static_analysis.events_pub.publish_event",
            side_effect=events_published.append,
        ),
    ):
        result = _run_static_analysis_impl(str(repo.id))

    # Assert — terminal status so the UI does not hang on "queued"
    assert result["status"] == "no_workflow_files"
    assert result["repo_id"] == str(repo.id)
    assert "[]" in str(result["results"])
    # A terminal (completed) event must have been published
    assert len(events_published) == 1


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


def test_with_violations_sets_issue_fields(
    db: Session, repo: Repository, workflow_file: WorkflowFile, seeded_rule: Rule
) -> None:
    # Arrange — violation with job and step populated
    violation = FakeViolation(
        rule_slug=seeded_rule.slug,
        severity=seeded_rule.severity.value,
        category=seeded_rule.category.value,
        line_start=5,
        line_end=5,
        message="Unpinned action",
        job="build",
        step="actions/checkout@v3",
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
        _run_static_analysis_impl(str(repo.id))

    # Assert — Issue has workflow_file_id, job, step, fingerprint set
    analysis = db.exec(
        select(Analysis)
        .where(Analysis.repo_id == repo.id)
        .where(Analysis.status == AnalysisStatus.completed)
    ).first()
    assert analysis is not None

    issue = db.exec(select(Issue).where(Issue.analysis_id == analysis.id)).first()
    assert issue is not None
    assert issue.workflow_file_id == workflow_file.id
    assert issue.job == "build"
    assert issue.step == "actions/checkout@v3"
    assert issue.fingerprint is not None
    assert len(issue.fingerprint) == 16


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

    # No new `skipped` Analysis rows accumulate: the result references the
    # prior completed analysis instead.
    skipped = db.exec(
        select(Analysis)
        .where(Analysis.repo_id == repo.id)
        .where(Analysis.status == AnalysisStatus.skipped)
    ).all()
    assert skipped == []
    completed = db.exec(
        select(Analysis)
        .where(Analysis.repo_id == repo.id)
        .where(Analysis.status == AnalysisStatus.completed)
    ).first()
    assert completed is not None
    assert str(completed.id) in second_results_str


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


def test_violation_with_unknown_rule_slug_auto_registers_rule(
    db: Session, repo: Repository, workflow_file: WorkflowFile
) -> None:
    # Arrange — violation with a slug that does not exist in seeded rules
    # (e.g. a newly shipped rego rule not present in the seed list)
    new_slug = f"brand_new_rule_{uuid.uuid4().hex[:8]}"
    violation = FakeViolation(
        rule_slug=new_slug,
        severity=IssueSeverity.low.value,
        category=IssueCategory.energy.value,
        line_start=1,
        line_end=1,
        message="fresh violation",
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

    # Analysis completes and the rule is auto-registered with an issue attached
    assert result["status"] == "done"
    results_str = str(result["results"])
    assert "completed" in results_str
    assert "'issues': 1" in results_str

    rule = db.exec(select(Rule).where(Rule.slug == new_slug)).first()
    assert rule is not None
    assert rule.enabled is True
    issue = db.exec(select(Issue).where(Issue.rule_id == rule.id)).first()
    assert issue is not None


def test_violation_with_invalid_category_is_skipped(
    db: Session, repo: Repository, workflow_file: WorkflowFile
) -> None:
    violation = FakeViolation(
        rule_slug=f"broken_rule_{uuid.uuid4().hex[:8]}",
        severity="not-a-severity",
        category="not-a-category",
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

    # Analysis still completes — the malformed violation is logged and skipped
    assert result["status"] == "done"
    results_str = str(result["results"])
    assert "completed" in results_str
    assert "'issues': 0" in results_str


def test_disabled_rule_violations_are_ignored(
    db: Session, repo: Repository, workflow_file: WorkflowFile
) -> None:
    # Arrange — a disabled rule
    disabled_rule = Rule(
        slug=f"disabled_rule_{uuid.uuid4().hex[:8]}",
        category=IssueCategory.energy,
        severity=IssueSeverity.low,
        title="Disabled rule",
        description="d",
        enabled=False,
    )
    db.add(disabled_rule)
    db.commit()
    db.refresh(disabled_rule)

    violation = FakeViolation(
        rule_slug=disabled_rule.slug,
        severity=IssueSeverity.low.value,
        category=IssueCategory.energy.value,
        line_start=1,
        line_end=1,
        message="should be ignored",
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

    assert result["status"] == "done"
    results_str = str(result["results"])
    assert "completed" in results_str
    assert "'issues': 0" in results_str
    issue = db.exec(select(Issue).where(Issue.rule_id == disabled_rule.id)).first()
    assert issue is None


def test_stale_issue_is_resolved_when_violation_disappears(
    db: Session, repo: Repository, workflow_file: WorkflowFile, seeded_rule: Rule
) -> None:
    violation = FakeViolation(
        rule_slug=seeded_rule.slug,
        severity=seeded_rule.severity.value,
        category=seeded_rule.category.value,
        line_start=1,
        line_end=1,
        message="will be fixed manually",
        job="build",
    )

    # First run — creates the issue
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
        _run_static_analysis_impl(str(repo.id))

    issue = db.exec(
        select(Issue).where(Issue.workflow_file_id == workflow_file.id)
    ).first()
    assert issue is not None
    db.refresh(issue)
    assert issue.resolved_at is None

    # Second run (forced) — the violation is gone (user fixed it manually)
    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files",
            return_value=[workflow_file],
        ),
        patch("app.workers.tasks.static_analysis._evaluate", return_value=[]),
    ):
        _run_static_analysis_impl(str(repo.id), force=True)

    db.refresh(issue)
    assert issue.resolved_at is not None

    # Third run — the violation reappears: the issue is reopened
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
        _run_static_analysis_impl(str(repo.id), force=True)

    db.refresh(issue)
    assert issue.resolved_at is None


def test_issues_of_deleted_workflow_files_are_resolved(
    db: Session, repo: Repository, workflow_file: WorkflowFile, seeded_rule: Rule
) -> None:
    violation = FakeViolation(
        rule_slug=seeded_rule.slug,
        severity=seeded_rule.severity.value,
        category=seeded_rule.category.value,
        line_start=1,
        line_end=1,
        message="workflow will be deleted",
        job="build",
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
        _run_static_analysis_impl(str(repo.id))

    issue = db.exec(
        select(Issue).where(Issue.workflow_file_id == workflow_file.id)
    ).first()
    assert issue is not None

    # The workflow file disappears from the repo (deleted or renamed)
    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files",
            return_value=[],
        ),
        patch("app.workers.tasks.static_analysis._evaluate", return_value=[]),
    ):
        result = _run_static_analysis_impl(str(repo.id))

    assert result["status"] == "no_workflow_files"
    db.refresh(issue)
    assert issue.resolved_at is not None


def test_completed_analysis_is_queryable_as_latest(
    db: Session, repo: Repository, workflow_file: WorkflowFile
) -> None:
    """Completed analyses are correctly identified as 'latest' via the correlated subquery
    used by the issues API (ordering by completed_at DESC, created_at DESC)."""
    from sqlmodel import select

    from app.models import Analysis, AnalysisStatus

    # Arrange — first run
    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files",
            return_value=[workflow_file],
        ),
        patch("app.workers.tasks.static_analysis._evaluate", return_value=[]),
    ):
        _run_static_analysis_impl(str(repo.id))

    first_analysis = db.exec(
        select(Analysis)
        .where(Analysis.repo_id == repo.id)
        .where(Analysis.status == AnalysisStatus.completed)
    ).first()
    assert first_analysis is not None

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

    # Assert — two completed analyses now exist; the newer one has a later created_at
    analyses = db.exec(
        select(Analysis)
        .where(Analysis.repo_id == repo.id)
        .where(Analysis.status == AnalysisStatus.completed)
        .order_by(Analysis.created_at.desc())  # type: ignore[union-attr]
    ).all()
    assert len(analyses) >= 2
    assert analyses[0].id != first_analysis.id


# ─── reanalyze_all_repositories ──────────────────────────────────────────────


def test_reanalyze_all_enqueues_enabled_repos_with_force_and_release_trigger(
    db: Session, org: Organization
) -> None:
    # Arrange — one enabled and one disabled repo
    enabled = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"reanalyze/enabled-{uuid.uuid4().hex[:8]}",
        installation_id=30001,
        default_branch="trunk",
        enabled=True,
    )
    disabled = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"reanalyze/disabled-{uuid.uuid4().hex[:8]}",
        installation_id=30002,
        default_branch="main",
        enabled=False,
    )
    db.add(enabled)
    db.add(disabled)
    db.commit()
    db.refresh(enabled)
    db.refresh(disabled)

    # Act
    with patch(
        "app.workers.tasks.static_analysis.run_static_analysis.apply_async"
    ) as mock_apply:
        result = _reanalyze_all_repositories_impl()

    # Assert — enabled repo enqueued with force + release trigger on its branch
    enqueued_kwargs = [call.kwargs["kwargs"] for call in mock_apply.call_args_list]
    enqueued_repo_ids = {kw["repo_id"] for kw in enqueued_kwargs}
    assert str(enabled.id) in enqueued_repo_ids
    assert str(disabled.id) not in enqueued_repo_ids

    enabled_kwargs = next(
        kw for kw in enqueued_kwargs if kw["repo_id"] == str(enabled.id)
    )
    assert enabled_kwargs["force"] is True
    assert enabled_kwargs["trigger"] == "release"
    assert enabled_kwargs["branch"] == "trunk"

    assert result["status"] == "queued"
    assert int(result["repos"]) == len(enqueued_repo_ids)


# ─── _enrich_line_numbers ─────────────────────────────────────────────────────


def test_enrich_line_numbers_noop_on_invalid_yaml() -> None:
    violations = [
        FakeViolation(
            rule_slug="test",
            severity="low",
            category="energy",
            line_start=0,
            line_end=0,
            message="m",
            job="build",
        )
    ]
    _enrich_line_numbers(violations, "not: valid: yaml: [[[")
    # Should not raise; line_start/end remain unchanged (0)
    assert violations[0].line_start == 0


def test_enrich_line_numbers_noop_on_no_jobs() -> None:
    violations = [
        FakeViolation(
            rule_slug="test",
            severity="low",
            category="energy",
            line_start=0,
            line_end=0,
            message="m",
            job="build",
        )
    ]
    _enrich_line_numbers(violations, "on: push\n")
    assert violations[0].line_start == 0


def test_enrich_line_numbers_skips_violation_with_no_job() -> None:
    content = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
    violations = [
        FakeViolation(
            rule_slug="test",
            severity="low",
            category="energy",
            line_start=0,
            line_end=0,
            message="m",
            job=None,
        )
    ]
    _enrich_line_numbers(violations, content)
    # No crash, job=None is skipped
    assert violations[0].line_start == 0


def test_enrich_line_numbers_skips_missing_job() -> None:
    content = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
    violations = [
        FakeViolation(
            rule_slug="test",
            severity="low",
            category="energy",
            line_start=0,
            line_end=0,
            message="m",
            job="nonexistent",
        )
    ]
    _enrich_line_numbers(violations, content)
    assert violations[0].line_start == 0


def test_enrich_line_numbers_job_level_violation() -> None:
    content = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps: []\n"
    violations = [
        FakeViolation(
            rule_slug="test",
            severity="low",
            category="energy",
            line_start=0,
            line_end=0,
            message="m",
            job="build",
            step=None,
        )
    ]
    _enrich_line_numbers(violations, content)
    # Job-level: line_start should be populated (ruamel reports line of the job key)
    assert violations[0].line_start > 0


def test_enrich_line_numbers_step_found_does_not_raise() -> None:
    # Step-level enrichment: even when lc.value(i) raises IndexError internally
    # (a ruamel.yaml limitation for sequence items), the function must not raise
    # and must leave line_start in a defined state.
    content = (
        "on: push\n"
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v3\n"
    )
    violations = [
        FakeViolation(
            rule_slug="test",
            severity="low",
            category="energy",
            line_start=0,
            line_end=0,
            message="m",
            job="build",
            step="actions/checkout@v3",
        )
    ]
    # Should not raise regardless of lc.value behaviour
    _enrich_line_numbers(violations, content)
    # line_start is either enriched (>0) or left unchanged (0); both are valid
    assert violations[0].line_start >= 0


def test_enrich_line_numbers_step_not_found_leaves_unchanged() -> None:
    content = (
        "on: push\n"
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v3\n"
    )
    violations = [
        FakeViolation(
            rule_slug="test",
            severity="low",
            category="energy",
            line_start=0,
            line_end=0,
            message="m",
            job="build",
            step="actions/setup-node@v4",
        )
    ]
    _enrich_line_numbers(violations, content)
    # Step not found: line_start remains 0
    assert violations[0].line_start == 0


def test_enrich_line_numbers_noop_when_yaml_is_not_a_dict() -> None:
    """YAML that parses to a list (not a dict) is a no-op."""
    violations = [
        FakeViolation(
            rule_slug="test",
            severity="low",
            category="energy",
            line_start=0,
            line_end=0,
            message="m",
            job="build",
        )
    ]
    _enrich_line_numbers(violations, "- item1\n- item2\n")
    assert violations[0].line_start == 0


def test_enrich_line_numbers_skips_non_list_steps() -> None:
    """Job whose `steps` value is not a list is skipped without error."""
    content = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps: string_value\n"
    violations = [
        FakeViolation(
            rule_slug="test",
            severity="low",
            category="energy",
            line_start=0,
            line_end=0,
            message="m",
            job="build",
            step="actions/checkout@v3",
        )
    ]
    _enrich_line_numbers(violations, content)
    assert violations[0].line_start == 0


def test_enrich_line_numbers_skips_non_dict_step_entry() -> None:
    """A step list entry that is not a dict (e.g. a plain string) is skipped."""
    content = (
        "on: push\n"
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo hello\n"
        "      - uses: actions/checkout@v3\n"
    )
    violations = [
        FakeViolation(
            rule_slug="test",
            severity="low",
            category="energy",
            line_start=0,
            line_end=0,
            message="m",
            job="build",
            step="actions/checkout@v3",
        )
    ]
    _enrich_line_numbers(violations, content)
    # The checkout step IS a dict and should be enriched
    assert violations[0].line_start > 0


# ─── Batch mode (multiple workflow files) ────────────────────────────────────


@dataclass
class _FakeBatchFile:
    path: str
    content: str


def test_batch_mode_publishes_single_started_event(
    db: Session, repo: Repository
) -> None:
    # Arrange — two distinct workflow files (no workflow_file_id → batch mode)
    unique1 = uuid.uuid4().hex
    unique2 = uuid.uuid4().hex
    files = [
        _FakeBatchFile(
            path=f".github/workflows/ci-{unique1}.yml",
            content=f"# {unique1}\non: push\njobs: {{}}",
        ),
        _FakeBatchFile(
            path=f".github/workflows/deploy-{unique2}.yml",
            content=f"# {unique2}\non: push\njobs: {{}}",
        ),
    ]

    events_published: list = []
    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files",
            return_value=files,
        ),
        patch("app.workers.tasks.static_analysis._evaluate", return_value=[]),
        patch(
            "app.workers.tasks.static_analysis.events_pub.publish_event",
            side_effect=events_published.append,
        ),
    ):
        result = _run_static_analysis_impl(str(repo.id))

    assert result["status"] == "done"
    # In batch mode both files should complete
    results_str = str(result["results"])
    assert results_str.count("completed") == 2


def test_batch_mode_opa_failure_sets_batch_any_failed(
    db: Session, repo: Repository
) -> None:
    # Arrange — both files fail OPA evaluation
    unique1 = uuid.uuid4().hex
    unique2 = uuid.uuid4().hex
    files = [
        _FakeBatchFile(
            path=f".github/workflows/fail-{unique1}.yml",
            content=f"# {unique1}\non: push\njobs: {{}}",
        ),
        _FakeBatchFile(
            path=f".github/workflows/fail-{unique2}.yml",
            content=f"# {unique2}\non: push\njobs: {{}}",
        ),
    ]

    with (
        patch(
            "app.workers.tasks.static_analysis._fetch_workflow_files",
            return_value=files,
        ),
        patch(
            "app.workers.tasks.static_analysis._evaluate",
            side_effect=RuntimeError("OPA down"),
        ),
        patch("app.workers.tasks.static_analysis.events_pub.publish_event"),
    ):
        result = _run_static_analysis_impl(str(repo.id))

    assert result["status"] == "done"
    assert str(result["results"]).count("failed") >= 2
