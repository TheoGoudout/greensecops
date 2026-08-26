"""Tests for the /api/v1/workflow-scans/ endpoints."""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import (
    Organization,
    Repository,
    ScanStatus,
    WorkflowFile,
    WorkflowScan,
)
from tests.fixtures import factories as f

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    return f.make_org(db)


@pytest.fixture()
def repo(db: Session, org: Organization) -> Repository:
    return f.make_repo(db, org, installation_id=55555)


@pytest.fixture()
def workflow_file(db: Session, repo: Repository) -> WorkflowFile:
    return f.make_workflow_file(db, repo, raw_content="on: push\njobs: {}")


@pytest.fixture()
def completed_analysis(
    db: Session, repo: Repository, workflow_file: WorkflowFile
) -> WorkflowScan:
    return f.make_scan(
        db,
        repo,
        workflow_file,
        status=ScanStatus.completed,
        score=85.0,
        grade="B",
        branch="main",
        content_hash=workflow_file.content_hash,
    )


# ─── GET /workflow-scans/ ───────────────────────────────────────────────────────────


def test_list_analyses_empty(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    # Arrange — fresh repo with no analyses
    fresh_repo = f.make_repo(db, f.make_org(db), installation_id=66666)

    # Act
    response = client.get(
        f"{settings.API_V1_STR}/workflow-scans/",
        params={"repo_id": str(fresh_repo.id)},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    assert response.json() == []


def test_list_analyses_with_data(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    completed_analysis: WorkflowScan,
    repo: Repository,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/workflow-scans/",
        params={"repo_id": str(repo.id)},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    ids = [a["id"] for a in data]
    assert str(completed_analysis.id) in ids


def test_list_analyses_filter_by_grade(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    completed_analysis: WorkflowScan,
    repo: Repository,
) -> None:
    # Act — filter by grade B
    response = client.get(
        f"{settings.API_V1_STR}/workflow-scans/",
        params={"repo_id": str(repo.id), "grade": "B"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert all(a["grade"] == "B" for a in data)
    assert any(a["id"] == str(completed_analysis.id) for a in data)


def test_list_analyses_filter_by_status(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    completed_analysis: WorkflowScan,
    repo: Repository,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/workflow-scans/",
        params={"repo_id": str(repo.id), "status": "completed"},
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert all(a["status"] == "completed" for a in data)
    assert any(a["id"] == str(completed_analysis.id) for a in data)


# ─── GET /analyses/{id} ───────────────────────────────────────────────────────


def test_get_analysis_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    completed_analysis: WorkflowScan,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/workflow-scans/{completed_analysis.id}",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(completed_analysis.id)
    assert body["grade"] == "B"
    assert body["status"] == "completed"


def test_get_scan_includes_workflow_path(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    completed_analysis: WorkflowScan,
    workflow_file: WorkflowFile,
    repo: Repository,
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/workflow-scans/{completed_analysis.id}",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["file_path"] == workflow_file.path
    assert body["repo_full_name"] == repo.full_name


def test_get_analysis_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/workflow-scans/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Workflow scan not found"


# ─── POST /analyses/trigger/{repo_id} ────────────────────────────────────────


def test_trigger_analysis_success(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
) -> None:
    # Act
    with patch(
        "app.workers.tasks.static_analysis.run_static_analysis.delay"
    ) as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/workflow-scans/trigger/{repo.id}",
            headers=superuser_token_headers,
        )

    # Assert
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["repo_id"] == str(repo.id)
    mock_delay.assert_called_once()
    assert mock_delay.call_args.kwargs.get("force") is True


def test_trigger_analysis_force_defaults_to_true(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
) -> None:
    # Manual trigger always forces — dedup bypass is the default
    with patch(
        "app.workers.tasks.static_analysis.run_static_analysis.delay"
    ) as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/workflow-scans/trigger/{repo.id}",
            headers=superuser_token_headers,
        )

    assert response.status_code == 202
    assert mock_delay.call_args.kwargs.get("force") is True


def test_trigger_analysis_can_opt_out_of_force(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
) -> None:
    # Callers can explicitly pass force=false to keep dedup active
    with patch(
        "app.workers.tasks.static_analysis.run_static_analysis.delay"
    ) as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/workflow-scans/trigger/{repo.id}",
            params={"force": "false"},
            headers=superuser_token_headers,
        )

    assert response.status_code == 202
    assert mock_delay.call_args.kwargs.get("force") is False


def test_trigger_analysis_repo_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    # Act
    with patch("app.workers.tasks.static_analysis.run_static_analysis.delay"):
        response = client.post(
            f"{settings.API_V1_STR}/workflow-scans/trigger/{uuid.uuid4()}",
            headers=superuser_token_headers,
        )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Repository not found"


# ─── POST /analyses/reanalyze-for-workflow/{workflow_file_id} ─────────────────


def test_reanalyze_for_workflow_success(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    workflow_file: WorkflowFile,
) -> None:
    # Act
    with patch(
        "app.workers.tasks.static_analysis.run_static_analysis.delay"
    ) as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/workflow-scans/reanalyze-for-workflow/{workflow_file.id}",
            headers=superuser_token_headers,
        )

    # Assert — the worker is scoped to just this workflow file, forced.
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["workflow_file_id"] == str(workflow_file.id)
    mock_delay.assert_called_once()
    assert mock_delay.call_args.kwargs.get("workflow_file_id") == str(workflow_file.id)
    assert mock_delay.call_args.kwargs.get("repo_id") == str(repo.id)
    assert mock_delay.call_args.kwargs.get("force") is True


def test_reanalyze_for_workflow_can_opt_out_of_force(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    workflow_file: WorkflowFile,
) -> None:
    with patch(
        "app.workers.tasks.static_analysis.run_static_analysis.delay"
    ) as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/workflow-scans/reanalyze-for-workflow/{workflow_file.id}",
            params={"force": "false"},
            headers=superuser_token_headers,
        )

    assert response.status_code == 202
    assert mock_delay.call_args.kwargs.get("force") is False


def test_reanalyze_for_workflow_not_found(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    with patch("app.workers.tasks.static_analysis.run_static_analysis.delay"):
        response = client.post(
            f"{settings.API_V1_STR}/workflow-scans/reanalyze-for-workflow/{uuid.uuid4()}",
            headers=superuser_token_headers,
        )

    assert response.status_code == 404
