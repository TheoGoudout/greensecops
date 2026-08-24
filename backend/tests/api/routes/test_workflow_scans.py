"""Tests for the /api/v1/analyses/ endpoints."""

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
    ScanTrigger,
    UserTier,
    WorkflowFile,
    WorkflowScan,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"analyses-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
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
        full_name=f"analysesowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=55555,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def workflow_file(db: Session, repo: Repository) -> WorkflowFile:
    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/ci.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@pytest.fixture()
def completed_analysis(
    db: Session, repo: Repository, workflow_file: WorkflowFile
) -> WorkflowScan:
    analysis = WorkflowScan(
        repo_id=repo.id,
        workflow_file_id=workflow_file.id,
        content_hash=workflow_file.content_hash,
        status=ScanStatus.completed,
        score=85.0,
        grade="B",
        triggered_by=ScanTrigger.manual,
        branch="main",
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


# ─── GET /analyses/ ───────────────────────────────────────────────────────────


def test_list_analyses_empty(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    # Arrange — fresh repo with no analyses
    fresh_org = Organization(
        name=f"no-analyses-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(fresh_org)
    db.commit()
    db.refresh(fresh_org)

    fresh_repo = Repository(
        org_id=fresh_org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"empty-analyses/repo-{uuid.uuid4().hex[:8]}",
        installation_id=66666,
    )
    db.add(fresh_repo)
    db.commit()
    db.refresh(fresh_repo)

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


def test_get_analysis_includes_workflow_path(
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
    assert body["workflow_file_path"] == workflow_file.path
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
