"""Tests for /api/v1/telemetry/ingest and /api/v1/telemetry/sample endpoints."""

import json
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.deps import verify_github_oidc_token
from app.core.config import settings
from app.main import app
from app.models import (
    DynamicEnrichment,
    Organization,
    OrgMember,
    OrgRole,
    Repository,
    TelemetryMetricSample,
    TelemetryPhase,
    TelemetryRun,
    UserTier,
)
from tests.utils.user import authentication_token_from_email, create_random_user

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


@pytest.fixture(autouse=True)
def _mock_dynamic_delay():
    """Completed-phase ingest enqueues dynamic analysis; stub the Celery call so
    tests never reach a broker/result backend (which is unavailable in CI)."""
    with patch("app.workers.tasks.dynamic_analysis.run_dynamic_analysis.delay") as mock:
        yield mock


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


def test_ingest_completed_enqueues_dynamic_analysis(
    client: TestClient, db: Session, repo: Repository, _mock_dynamic_delay
) -> None:
    _override_oidc(_oidc_claims(repo.full_name, run_id=2101))
    try:
        response = client.post(
            f"{settings.API_V1_STR}/telemetry/ingest",
            json=_ingest_payload(run_id=2101, phase="completed"),
            headers={"Authorization": "Bearer mock-oidc-token"},
        )
    finally:
        _clear_oidc()

    assert response.status_code == 201
    run_id = response.json()["telemetry_run_id"]
    _mock_dynamic_delay.assert_called_once_with(run_id)


def test_ingest_started_does_not_enqueue_dynamic_analysis(
    client: TestClient, db: Session, repo: Repository, _mock_dynamic_delay
) -> None:
    _override_oidc(_oidc_claims(repo.full_name, run_id=2102))
    try:
        response = client.post(
            f"{settings.API_V1_STR}/telemetry/ingest",
            json=_ingest_payload(run_id=2102, phase="started"),
            headers={"Authorization": "Bearer mock-oidc-token"},
        )
    finally:
        _clear_oidc()

    assert response.status_code == 201
    _mock_dynamic_delay.assert_not_called()


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


def test_sample_stores_top_processes_as_json(
    client: TestClient, db: Session, repo: Repository
) -> None:
    _override_oidc(_oidc_claims(repo.full_name, run_id=6002))
    top_processes = [
        {"pid": 1, "name": "node", "cpu_percent": 42.0, "mem_percent": 5.0},
        {"pid": 2, "name": "bash", "cpu_percent": 1.0, "mem_percent": 0.1},
    ]
    try:
        response = client.post(
            f"{settings.API_V1_STR}/telemetry/sample",
            json={
                "workflow_run_id": 6002,
                "cpu_percent": 12.0,
                "top_processes": top_processes,
            },
            headers={"Authorization": "Bearer mock-oidc-token"},
        )
    finally:
        _clear_oidc()

    assert response.status_code == 200

    sample = db.exec(
        select(TelemetryMetricSample)
        .where(TelemetryMetricSample.repo_id == repo.id)
        .where(TelemetryMetricSample.workflow_run_id == 6002)
    ).one()
    assert json.loads(sample.top_processes) == top_processes


def test_sample_omits_top_processes_when_absent(
    client: TestClient, db: Session, repo: Repository
) -> None:
    _override_oidc(_oidc_claims(repo.full_name, run_id=6003))
    try:
        response = client.post(
            f"{settings.API_V1_STR}/telemetry/sample",
            json={"workflow_run_id": 6003, "cpu_percent": 12.0},
            headers={"Authorization": "Bearer mock-oidc-token"},
        )
    finally:
        _clear_oidc()

    assert response.status_code == 200

    sample = db.exec(
        select(TelemetryMetricSample)
        .where(TelemetryMetricSample.repo_id == repo.id)
        .where(TelemetryMetricSample.workflow_run_id == 6003)
    ).one()
    assert sample.top_processes is None


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


# ─── Read / analyze helpers ──────────────────────────────────────────────────


def _seed_run(
    db: Session,
    repo: Repository,
    run_id: int,
    *,
    phase: TelemetryPhase = TelemetryPhase.completed,
    vcpus: int = 8,
    ram_percent: float = 20.0,
) -> TelemetryRun:
    run = TelemetryRun(
        repo_id=repo.id,
        workflow_run_id=run_id,
        runner_specs=json.dumps({"vcpus": vcpus, "ram_total_gb": 16.0}),
        metrics=json.dumps({"cpu_percent": 12.0, "ram_percent": ram_percent}),
        phase=phase,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _seed_sample(db: Session, repo: Repository, run_id: int, cpu: float) -> None:
    db.add(
        TelemetryMetricSample(
            repo_id=repo.id,
            workflow_run_id=run_id,
            cpu_percent=cpu,
            ram_used_mb=2048.0,
            disk_used_gb=4.0,
            net_bytes_sent=1000,
            net_bytes_recv=2000,
        )
    )
    db.commit()


def _seed_enrichment(db: Session, repo: Repository, run: TelemetryRun) -> None:
    db.add(
        DynamicEnrichment(
            repo_id=repo.id,
            telemetry_run_id=run.id,
            rule_slug="runner_sizing",
            evidence="vCPUs=8, CPU=12.0%, RAM=20.0%",
            recommendation="Consider downsizing from 8 vCPUs — actual usage is low",
        )
    )
    db.commit()


# ─── GET /summary ────────────────────────────────────────────────────────────


def test_summary_computes_averages_and_runs(
    client: TestClient,
    db: Session,
    repo: Repository,
    superuser_token_headers: dict[str, str],
) -> None:
    run = _seed_run(db, repo, 10001, ram_percent=20.0)
    _seed_run(db, repo, 10002, ram_percent=40.0)
    _seed_sample(db, repo, 10001, cpu=10.0)
    _seed_sample(db, repo, 10001, cpu=30.0)
    _seed_enrichment(db, repo, run)

    response = client.get(
        f"{settings.API_V1_STR}/telemetry/summary/{repo.id}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200, response.json()
    body = response.json()
    avg = body["average"]
    assert avg["run_count"] == 2
    assert avg["sample_count"] == 2
    assert avg["avg_cpu_percent"] == pytest.approx(20.0)  # (10 + 30) / 2
    assert avg["avg_ram_percent"] == pytest.approx(30.0)  # (20 + 40) / 2
    assert avg["avg_vcpus"] == pytest.approx(8.0)
    assert len(body["runs"]) == 2

    enriched_run = next(r for r in body["runs"] if r["workflow_run_id"] == 10001)
    assert enriched_run["metrics"]["ram_percent"] == 20.0
    assert enriched_run["runner_specs"]["vcpus"] == 8
    assert len(enriched_run["enrichments"]) == 1
    assert enriched_run["enrichments"][0]["rule_slug"] == "runner_sizing"


def test_summary_empty_repo(
    client: TestClient,
    repo: Repository,
    superuser_token_headers: dict[str, str],
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/telemetry/summary/{repo.id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["average"]["run_count"] == 0
    assert body["average"]["avg_cpu_percent"] is None
    assert body["runs"] == []


def test_summary_pagination(
    client: TestClient,
    db: Session,
    repo: Repository,
    superuser_token_headers: dict[str, str],
) -> None:
    for i in range(3):
        _seed_run(db, repo, 11000 + i)

    response = client.get(
        f"{settings.API_V1_STR}/telemetry/summary/{repo.id}?limit=2&skip=0",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["average"]["run_count"] == 3  # averages cover all runs
    assert len(body["runs"]) == 2  # page is limited


def test_summary_foreign_repo_returns_404(
    client: TestClient,
    db: Session,
    repo: Repository,
) -> None:
    """A user with no membership in the repo's org cannot read its telemetry."""
    user = create_random_user(db)
    headers = authentication_token_from_email(client=client, email=user.email, db=db)

    response = client.get(
        f"{settings.API_V1_STR}/telemetry/summary/{repo.id}",
        headers=headers,
    )
    assert response.status_code == 404


# ─── GET /findings ───────────────────────────────────────────────────────────


def test_findings_returns_enrichments(
    client: TestClient,
    db: Session,
    org: Organization,
    repo: Repository,
) -> None:
    run = _seed_run(db, repo, 12001)
    _seed_enrichment(db, repo, run)

    # A member of the repo's org (non-superuser) can read findings.
    user = create_random_user(db)
    db.add(OrgMember(org_id=org.id, user_id=user.id, role=OrgRole.member))
    db.commit()
    headers = authentication_token_from_email(client=client, email=user.email, db=db)

    response = client.get(
        f"{settings.API_V1_STR}/telemetry/findings/{repo.id}",
        headers=headers,
    )
    assert response.status_code == 200
    findings = response.json()
    assert len(findings) == 1
    assert findings[0]["rule_slug"] == "runner_sizing"
    assert findings[0]["workflow_run_id"] == 12001
    assert "recommendation" in findings[0]


# ─── POST /analyze ───────────────────────────────────────────────────────────


def test_analyze_enqueues_completed_runs(
    client: TestClient,
    db: Session,
    repo: Repository,
    superuser_token_headers: dict[str, str],
    _mock_dynamic_delay,
) -> None:
    _seed_run(db, repo, 13001, phase=TelemetryPhase.completed)
    _seed_run(db, repo, 13002, phase=TelemetryPhase.completed)
    _seed_run(db, repo, 13003, phase=TelemetryPhase.started)  # not enqueued

    response = client.post(
        f"{settings.API_V1_STR}/telemetry/analyze/{repo.id}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 202, response.json()
    assert response.json()["runs"] == 2
    assert _mock_dynamic_delay.call_count == 2


def test_analyze_inaccessible_repo_returns_403(
    client: TestClient,
    db: Session,
    repo: Repository,
    superuser_token_headers: dict[str, str],
) -> None:
    repo.is_accessible = False
    db.add(repo)
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/telemetry/analyze/{repo.id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 403
