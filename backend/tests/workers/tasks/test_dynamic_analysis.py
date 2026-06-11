"""Unit tests for the dynamic_analysis Celery task."""

import json
import uuid
from unittest.mock import patch

import pytest
from sqlmodel import Session

from app.models import (
    Analysis,
    AnalysisStatus,
    AnalysisTrigger,
    Organization,
    Repository,
    TelemetryRun,
    UserTier,
    WorkflowFile,
)
from app.workers.tasks.dynamic_analysis import _run_dynamic_analysis_impl

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    org = Organization(name=f"dyn-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@pytest.fixture()
def repo(db: Session, org: Organization) -> Repository:
    repository = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"dynowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=99999,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


def _make_telemetry_run(
    db: Session,
    repo: Repository,
    *,
    vcpus: int = 2,
    cpu_percent: float = 50.0,
    ram_percent: float = 50.0,
) -> TelemetryRun:
    run = TelemetryRun(
        repo_id=repo.id,
        workflow_run_id=int(uuid.uuid4().int % 10**6),
        runner_specs=json.dumps({"vcpus": vcpus, "os": "Linux"}),
        metrics=json.dumps({"cpu_percent": cpu_percent, "ram_percent": ram_percent}),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _make_completed_analysis(db: Session, repo: Repository) -> Analysis:
    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/ci.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)

    analysis = Analysis(
        repo_id=repo.id,
        workflow_file_id=wf.id,
        content_hash=wf.content_hash,
        status=AnalysisStatus.completed,
        score=85.0,
        grade="B",
        triggered_by=AnalysisTrigger.manual,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


# ─── Tests ───────────────────────────────────────────────────────────────────


def test_run_dynamic_analysis_returns_completed(db: Session, repo: Repository) -> None:
    # Arrange
    run = _make_telemetry_run(db, repo)

    # Act — call the underlying function directly, bypassing Celery
    result = _run_dynamic_analysis_impl(str(run.id))

    # Assert
    assert result["status"] == "completed"
    assert result["telemetry_run_id"] == str(run.id)


def test_run_dynamic_analysis_not_found_returns_error(db: Session) -> None:  # noqa: ARG001
    # Arrange — a UUID that doesn't exist
    missing_id = str(uuid.uuid4())

    # Act
    result = _run_dynamic_analysis_impl(missing_id)

    # Assert
    assert result["status"] == "error"
    assert result["detail"] == "telemetry_run_not_found"


def test_run_dynamic_analysis_no_enrichment_for_small_runner(
    db: Session, repo: Repository
) -> None:
    # Arrange — 2 vCPUs at 50% CPU: below the 8-vCPU threshold, no enrichment
    run = _make_telemetry_run(db, repo, vcpus=2, cpu_percent=50.0, ram_percent=50.0)

    # Act
    result = _run_dynamic_analysis_impl(str(run.id))

    # Assert
    assert result["status"] == "completed"
    assert int(result["enrichments"]) == 0


def test_run_dynamic_analysis_enrichment_for_oversized_runner(
    db: Session, repo: Repository
) -> None:
    # Arrange — 16 vCPUs but CPU=10% and RAM=20%: clearly oversized
    run = _make_telemetry_run(db, repo, vcpus=16, cpu_percent=10.0, ram_percent=20.0)

    # Act
    result = _run_dynamic_analysis_impl(str(run.id))

    # Assert
    assert result["status"] == "completed"
    assert int(result["enrichments"]) == 1


def test_run_dynamic_analysis_no_enrichment_when_cpu_high(
    db: Session, repo: Repository
) -> None:
    # Arrange — 8 vCPUs but CPU=80%: runner is being used
    run = _make_telemetry_run(db, repo, vcpus=8, cpu_percent=80.0, ram_percent=20.0)

    # Act
    result = _run_dynamic_analysis_impl(str(run.id))

    # Assert
    assert int(result["enrichments"]) == 0


def test_run_dynamic_analysis_no_enrichment_when_ram_high(
    db: Session, repo: Repository
) -> None:
    # Arrange — 8 vCPUs, CPU low but RAM=50%: above 30% threshold
    run = _make_telemetry_run(db, repo, vcpus=8, cpu_percent=10.0, ram_percent=50.0)

    # Act
    result = _run_dynamic_analysis_impl(str(run.id))

    # Assert
    assert int(result["enrichments"]) == 0


def test_run_dynamic_analysis_logs_enrichment_when_analysis_exists(
    db: Session, repo: Repository
) -> None:
    # Arrange — oversized runner + a completed analysis to attach to
    _make_completed_analysis(db, repo)
    run = _make_telemetry_run(db, repo, vcpus=16, cpu_percent=5.0, ram_percent=10.0)

    # Act — verify logger.info is called with enrichment info
    with patch("app.workers.tasks.dynamic_analysis.logger") as mock_logger:
        result = _run_dynamic_analysis_impl(str(run.id))

    # Assert
    assert result["status"] == "completed"
    assert int(result["enrichments"]) == 1
    # The enrichment log line should have been called
    info_calls = [str(c) for c in mock_logger.info.call_args_list]
    assert any("Dynamic enrichment" in c for c in info_calls)


def test_run_dynamic_analysis_empty_specs_and_metrics(
    db: Session, repo: Repository
) -> None:
    # Arrange — run with no specs/metrics (edge case: nulls)
    run = TelemetryRun(
        repo_id=repo.id,
        workflow_run_id=int(uuid.uuid4().int % 10**6),
        runner_specs=None,
        metrics=None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Act — should not raise
    result = _run_dynamic_analysis_impl(str(run.id))

    # Assert — defaults kick in: vcpus=0, so no oversizing signal
    assert result["status"] == "completed"
    assert int(result["enrichments"]) == 0
