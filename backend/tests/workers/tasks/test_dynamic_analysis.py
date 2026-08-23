"""Unit tests for the dynamic_analysis Celery task."""

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, select

from app.models import (
    Analysis,
    AnalysisStatus,
    AnalysisTrigger,
    DynamicAnalysisStatus,
    DynamicEnrichment,
    Organization,
    Repository,
    TelemetryRun,
    UserTier,
    WorkflowFile,
)
from app.services.opa.evaluator import CiTelemetryOpaViolation
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
        metrics=json.dumps(
            {"cpu_load_percent": cpu_percent, "ram_percent": ram_percent}
        ),
        # Ingest marks completed-phase rows queued before enqueuing the worker.
        dynamic_status=DynamicAnalysisStatus.queued,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _patch_evaluate(violations: list[CiTelemetryOpaViolation]) -> Any:
    return patch(
        "app.workers.tasks.dynamic_analysis._evaluate",
        new=AsyncMock(return_value=violations),
    )


def _underutilized_violation(vcpus: int, cpu_percent: float, ram_percent: float) -> Any:
    return CiTelemetryOpaViolation(
        rule_slug="runner_underutilized",
        severity="medium",
        category="energy",
        evidence=f"vCPUs={vcpus}, CPU={cpu_percent:.1f}%, RAM={ram_percent:.1f}%",
        recommendation=f"Consider downsizing from {vcpus} vCPUs — measured usage during the run was low.",
    )


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
    with _patch_evaluate([]):
        result = _run_dynamic_analysis_impl(str(run.id))

    # Assert
    assert result["status"] == "completed"
    assert result["telemetry_run_id"] == str(run.id)
    # The machine drove the row queued -> running -> enriched.
    db.refresh(run)
    assert run.dynamic_status == DynamicAnalysisStatus.enriched


def test_run_dynamic_analysis_marks_failed_on_error(
    db: Session, repo: Repository
) -> None:
    run = _make_telemetry_run(db, repo)
    with patch(
        "app.workers.tasks.dynamic_analysis._enrich",
        side_effect=RuntimeError("boom"),
    ):
        result = _run_dynamic_analysis_impl(str(run.id))
    assert result["status"] == "failed"
    db.refresh(run)
    assert run.dynamic_status == DynamicAnalysisStatus.failed


def test_run_dynamic_analysis_not_found_returns_error(db: Session) -> None:
    # Arrange — a UUID that doesn't exist
    missing_id = str(uuid.uuid4())

    # Act
    result = _run_dynamic_analysis_impl(missing_id)

    # Assert
    assert result["status"] == "error"
    assert result["detail"] == "telemetry_run_not_found"


def test_run_dynamic_analysis_persists_enrichment_for_violation(
    db: Session, repo: Repository
) -> None:
    # Arrange — the OPA evaluator flags an oversized/idle runner. Whether a
    # given vcpus/cpu/ram combination actually crosses the Rego rule's
    # thresholds is verified separately against a real OPA container (see the
    # cloud/terraform rule verification convention); this test covers what
    # this task does with whatever the evaluator returns.
    run = _make_telemetry_run(db, repo, vcpus=16, cpu_percent=10.0, ram_percent=20.0)

    # Act
    with _patch_evaluate([_underutilized_violation(16, 10.0, 20.0)]):
        result = _run_dynamic_analysis_impl(str(run.id))

    # Assert
    assert result["status"] == "completed"
    assert int(result["enrichments"]) == 1


def test_run_dynamic_analysis_logs_enrichment_when_analysis_exists(
    db: Session, repo: Repository
) -> None:
    # Arrange — a violation + a completed analysis to attach the enrichment to
    _make_completed_analysis(db, repo)
    run = _make_telemetry_run(db, repo, vcpus=16, cpu_percent=5.0, ram_percent=10.0)

    # Act — verify logger.info is called with enrichment info
    with (
        _patch_evaluate([_underutilized_violation(16, 5.0, 10.0)]),
        patch("app.workers.tasks.dynamic_analysis.logger") as mock_logger,
    ):
        result = _run_dynamic_analysis_impl(str(run.id))

    # Assert
    assert result["status"] == "completed"
    assert int(result["enrichments"]) == 1
    # The enrichment log line should have been called
    info_calls = [str(c) for c in mock_logger.info.call_args_list]
    assert any("Dynamic enrichment" in c for c in info_calls)


def test_run_dynamic_analysis_persists_enrichment_linked_to_analysis(
    db: Session, repo: Repository
) -> None:
    # Arrange — a violation + a completed analysis to attach the enrichment to.
    analysis = _make_completed_analysis(db, repo)
    run = _make_telemetry_run(db, repo, vcpus=16, cpu_percent=5.0, ram_percent=10.0)

    # Act
    with _patch_evaluate([_underutilized_violation(16, 5.0, 10.0)]):
        result = _run_dynamic_analysis_impl(str(run.id))

    # Assert — a DynamicEnrichment row is persisted, linked to run + analysis.
    assert int(result["enrichments"]) == 1
    rows = db.exec(
        select(DynamicEnrichment).where(DynamicEnrichment.telemetry_run_id == run.id)
    ).all()
    assert len(rows) == 1
    assert rows[0].rule_slug == "runner_underutilized"
    assert rows[0].analysis_id == analysis.id
    assert rows[0].repo_id == repo.id


def test_run_dynamic_analysis_is_idempotent_on_rerun(
    db: Session, repo: Repository
) -> None:
    run = _make_telemetry_run(db, repo, vcpus=16, cpu_percent=5.0, ram_percent=10.0)
    with _patch_evaluate([_underutilized_violation(16, 5.0, 10.0)]):
        _run_dynamic_analysis_impl(str(run.id))
        _run_dynamic_analysis_impl(str(run.id))
    rows = db.exec(
        select(DynamicEnrichment).where(DynamicEnrichment.telemetry_run_id == run.id)
    ).all()
    # Re-running replaces rather than duplicating.
    assert len(rows) == 1


def test_run_dynamic_analysis_persists_nothing_when_no_signal(
    db: Session, repo: Repository
) -> None:
    run = _make_telemetry_run(db, repo, vcpus=2, cpu_percent=50.0, ram_percent=50.0)
    with _patch_evaluate([]):
        _run_dynamic_analysis_impl(str(run.id))
    rows = db.exec(
        select(DynamicEnrichment).where(DynamicEnrichment.telemetry_run_id == run.id)
    ).all()
    assert rows == []


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
    with _patch_evaluate([]):
        result = _run_dynamic_analysis_impl(str(run.id))

    # Assert
    assert result["status"] == "completed"
    assert int(result["enrichments"]) == 0
