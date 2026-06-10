"""Tests for the /api/v1/telemetry/ingest endpoint."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import Organization, Repository, TelemetryRun, UserTier

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    org = Organization(name=f"test-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@pytest.fixture()
def repo(db: Session, org: Organization) -> Repository:
    repository = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"testowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=12345,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


def _base_payload(repo_full_name: str, run_id: int = 1001) -> dict:
    return {
        "workflow_run_id": run_id,
        "repository": repo_full_name,
        "branch": "main",
        "commit_sha": "abc123",
        "workflow_name": "CI",
        "runner_specs": {"os": "Linux", "vcpus": 2, "ram_total_gb": 7.0},
        "metrics": {"cpu_percent": 45.0, "ram_percent": 60.0},
    }


# ─── Tests ───────────────────────────────────────────────────────────────────


def test_ingest_telemetry_creates_run(
    client: TestClient, db: Session, repo: Repository
) -> None:
    # Arrange
    payload = _base_payload(repo.full_name, run_id=2001)

    # Act
    response = client.post(
        f"{settings.API_V1_STR}/telemetry/ingest",
        json=payload,
        headers={"Authorization": "Bearer fake-token"},
    )

    # Assert
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "accepted"
    assert "telemetry_run_id" in body

    run_id = uuid.UUID(body["telemetry_run_id"])
    saved = db.get(TelemetryRun, run_id)
    assert saved is not None
    assert saved.workflow_run_id == 2001
    assert saved.repo_id == repo.id
    specs = json.loads(saved.runner_specs or "{}")
    assert specs["vcpus"] == 2


def test_ingest_telemetry_unknown_repo_accepted_silently(
    client: TestClient,
) -> None:
    # Arrange — repo that was never registered
    payload = _base_payload("ghost-owner/ghost-repo", run_id=3001)

    # Act
    response = client.post(
        f"{settings.API_V1_STR}/telemetry/ingest",
        json=payload,
        headers={"Authorization": "Bearer fake-token"},
    )

    # Assert — non-fatal: still 201, but flagged
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "accepted"
    assert body.get("note") == "repository_not_registered"


def test_ingest_telemetry_duplicate_run_ignored(
    client: TestClient, db: Session, repo: Repository
) -> None:
    # Arrange — send the same run_id twice
    payload = _base_payload(repo.full_name, run_id=4001)

    # Act
    first = client.post(
        f"{settings.API_V1_STR}/telemetry/ingest",
        json=payload,
        headers={"Authorization": "Bearer fake-token"},
    )
    second = client.post(
        f"{settings.API_V1_STR}/telemetry/ingest",
        json=payload,
        headers={"Authorization": "Bearer fake-token"},
    )

    # Assert — both calls succeed; second is a no-op
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json().get("note") == "duplicate_run"

    # Only one row in the DB
    from sqlmodel import select

    runs = db.exec(
        select(TelemetryRun)
        .where(TelemetryRun.repo_id == repo.id)
        .where(TelemetryRun.workflow_run_id == 4001)
    ).all()
    assert len(runs) == 1


def test_ingest_telemetry_missing_url_fields_rejected(
    client: TestClient,
) -> None:
    # Arrange — workflow_run_id is required (int); send string → validation error
    payload = {
        "workflow_run_id": "not-an-int",
        "repository": "owner/repo",
    }

    # Act
    response = client.post(
        f"{settings.API_V1_STR}/telemetry/ingest",
        json=payload,
        headers={"Authorization": "Bearer fake-token"},
    )

    # Assert — FastAPI returns 422 on schema validation failure
    assert response.status_code == 422


def test_ingest_telemetry_stores_metrics_json(
    client: TestClient, db: Session, repo: Repository
) -> None:
    # Arrange
    metrics = {
        "cpu_percent": 12.5,
        "ram_used_mb": 512.0,
        "ram_percent": 25.0,
        "net_bytes_sent": 1024,
        "net_bytes_recv": 2048,
    }
    payload = _base_payload(repo.full_name, run_id=5001)
    payload["metrics"] = metrics

    # Act
    response = client.post(
        f"{settings.API_V1_STR}/telemetry/ingest",
        json=payload,
        headers={"Authorization": "Bearer fake-token"},
    )

    # Assert
    assert response.status_code == 201
    run_id = uuid.UUID(response.json()["telemetry_run_id"])
    saved = db.get(TelemetryRun, run_id)
    assert saved is not None
    stored_metrics = json.loads(saved.metrics or "{}")
    assert stored_metrics["cpu_percent"] == 12.5
    assert stored_metrics["ram_percent"] == 25.0
