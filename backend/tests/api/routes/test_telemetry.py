"""Tests for /api/v1/telemetry/ingest and /api/v1/telemetry/sample endpoints."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.deps import verify_github_oidc_token
from app.core.config import settings
from app.main import app
from app.models import (
    Organization,
    Repository,
    TelemetryMetricSample,
    TelemetryRun,
    UserTier,
)

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _oidc_claims(repo_full_name: str, run_id: int = 1001) -> dict:
    return {
        "repository": repo_full_name,
        "repository_owner": repo_full_name.split("/")[0],
        "workflow": "CI",
        "ref": "refs/heads/main",
        "sha": "abc123def456",
        "run_id": str(run_id),
        "iss": "https://token.actions.githubusercontent.com",
        "aud": "greensecops",
    }


def _override_oidc(claims: dict) -> None:
    app.dependency_overrides[verify_github_oidc_token] = lambda: claims


def _clear_oidc() -> None:
    app.dependency_overrides.pop(verify_github_oidc_token, None)


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


def _ingest_payload(run_id: int = 1001, phase: str = "completed") -> dict:
    return {
        "workflow_run_id": run_id,
        "branch": "main",
        "commit_sha": "abc123",
        "workflow_name": "CI",
        "runner_specs": {"os": "Linux", "vcpus": 2, "ram_total_gb": 7.0},
        "metrics": {"cpu_percent": 45.0, "ram_percent": 60.0},
        "phase": phase,
    }


# ─── /ingest ─────────────────────────────────────────────────────────────────


def test_ingest_creates_run(client: TestClient, db: Session, repo: Repository) -> None:
    _override_oidc(_oidc_claims(repo.full_name, run_id=2001))
    try:
        response = client.post(
            f"{settings.API_V1_STR}/telemetry/ingest",
            json=_ingest_payload(run_id=2001),
            headers={"Authorization": "Bearer mock-oidc-token"},
        )
    finally:
        _clear_oidc()

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "accepted"
    assert "telemetry_run_id" in body

    saved = db.get(TelemetryRun, uuid.UUID(body["telemetry_run_id"]))
    assert saved is not None
    assert saved.workflow_run_id == 2001
    assert saved.repo_id == repo.id
    assert saved.phase == "completed"
    specs = json.loads(saved.runner_specs or "{}")
    assert specs["vcpus"] == 2


def test_ingest_unknown_repo_accepted_silently(client: TestClient) -> None:
    _override_oidc(_oidc_claims("ghost/ghost-repo", run_id=3001))
    try:
        response = client.post(
            f"{settings.API_V1_STR}/telemetry/ingest",
            json=_ingest_payload(run_id=3001),
            headers={"Authorization": "Bearer mock-oidc-token"},
        )
    finally:
        _clear_oidc()

    assert response.status_code == 201
    assert response.json().get("note") == "repository_not_registered"


def test_ingest_duplicate_run_phase_ignored(
    client: TestClient, db: Session, repo: Repository
) -> None:
    _override_oidc(_oidc_claims(repo.full_name, run_id=4001))
    payload = _ingest_payload(run_id=4001, phase="started")
    try:
        first = client.post(
            f"{settings.API_V1_STR}/telemetry/ingest",
            json=payload,
            headers={"Authorization": "Bearer mock-oidc-token"},
        )
        second = client.post(
            f"{settings.API_V1_STR}/telemetry/ingest",
            json=payload,
            headers={"Authorization": "Bearer mock-oidc-token"},
        )
    finally:
        _clear_oidc()

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json().get("note") == "duplicate_run_phase"

    runs = db.exec(
        select(TelemetryRun)
        .where(TelemetryRun.repo_id == repo.id)
        .where(TelemetryRun.workflow_run_id == 4001)
        .where(TelemetryRun.phase == "started")
    ).all()
    assert len(runs) == 1


def test_ingest_started_and_completed_both_stored(
    client: TestClient, db: Session, repo: Repository
) -> None:
    _override_oidc(_oidc_claims(repo.full_name, run_id=5001))
    try:
        client.post(
            f"{settings.API_V1_STR}/telemetry/ingest",
            json=_ingest_payload(run_id=5001, phase="started"),
            headers={"Authorization": "Bearer mock-oidc-token"},
        )
        client.post(
            f"{settings.API_V1_STR}/telemetry/ingest",
            json=_ingest_payload(run_id=5001, phase="completed"),
            headers={"Authorization": "Bearer mock-oidc-token"},
        )
    finally:
        _clear_oidc()

    runs = db.exec(
        select(TelemetryRun)
        .where(TelemetryRun.repo_id == repo.id)
        .where(TelemetryRun.workflow_run_id == 5001)
    ).all()
    assert len(runs) == 2
    assert {r.phase for r in runs} == {"started", "completed"}


def test_ingest_missing_oidc_returns_401(client: TestClient) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/telemetry/ingest",
        json=_ingest_payload(run_id=9001),
    )
    assert response.status_code == 401


def test_ingest_invalid_payload_returns_422(client: TestClient) -> None:
    _override_oidc(_oidc_claims("owner/repo"))
    try:
        response = client.post(
            f"{settings.API_V1_STR}/telemetry/ingest",
            json={"workflow_run_id": "not-an-int"},
            headers={"Authorization": "Bearer mock-oidc-token"},
        )
    finally:
        _clear_oidc()
    assert response.status_code == 422


# ─── /sample ─────────────────────────────────────────────────────────────────


def test_sample_stores_metrics(
    client: TestClient, db: Session, repo: Repository
) -> None:
    _override_oidc(_oidc_claims(repo.full_name, run_id=6001))
    try:
        response = client.post(
            f"{settings.API_V1_STR}/telemetry/sample",
            json={
                "workflow_run_id": 6001,
                "cpu_percent": 33.5,
                "ram_used_mb": 1024.0,
                "disk_used_gb": 5.2,
                "net_bytes_sent": 4096,
                "net_bytes_recv": 8192,
            },
            headers={"Authorization": "Bearer mock-oidc-token"},
        )
    finally:
        _clear_oidc()

    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    samples = db.exec(
        select(TelemetryMetricSample)
        .where(TelemetryMetricSample.repo_id == repo.id)
        .where(TelemetryMetricSample.workflow_run_id == 6001)
    ).all()
    assert len(samples) == 1
    assert samples[0].cpu_percent == pytest.approx(33.5)
    assert samples[0].ram_used_mb == pytest.approx(1024.0)


def test_sample_unknown_repo_returns_ok(client: TestClient) -> None:
    _override_oidc(_oidc_claims("ghost/repo", run_id=7001))
    try:
        response = client.post(
            f"{settings.API_V1_STR}/telemetry/sample",
            json={"workflow_run_id": 7001, "cpu_percent": 10.0},
            headers={"Authorization": "Bearer mock-oidc-token"},
        )
    finally:
        _clear_oidc()

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_sample_missing_oidc_returns_401(client: TestClient) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/telemetry/sample",
        json={"workflow_run_id": 8001},
    )
    assert response.status_code == 401


def test_sample_multiple_inserts_no_dedup(
    client: TestClient, db: Session, repo: Repository
) -> None:
    _override_oidc(_oidc_claims(repo.full_name, run_id=9001))
    try:
        for _ in range(3):
            client.post(
                f"{settings.API_V1_STR}/telemetry/sample",
                json={"workflow_run_id": 9001, "cpu_percent": 50.0},
                headers={"Authorization": "Bearer mock-oidc-token"},
            )
    finally:
        _clear_oidc()

    samples = db.exec(
        select(TelemetryMetricSample)
        .where(TelemetryMetricSample.repo_id == repo.id)
        .where(TelemetryMetricSample.workflow_run_id == 9001)
    ).all()
    assert len(samples) == 3
