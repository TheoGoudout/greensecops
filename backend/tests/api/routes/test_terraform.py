"""Tests for the /api/v1/terraform-roots/ endpoints."""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    AnalysisTrigger,
    IssueCategory,
    IssueSeverity,
    Organization,
    Repository,
    Rule,
    RuleDomain,
    ScanStatus,
    TerraformFinding,
    TerraformRoot,
    TerraformScan,
    UserTier,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"tfapi-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
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
        full_name=f"tfapiowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=66666,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def terraform_root(db: Session, repo: Repository) -> TerraformRoot:
    root = TerraformRoot(repo_id=repo.id, root_path=f"infra/{uuid.uuid4().hex[:8]}")
    db.add(root)
    db.commit()
    db.refresh(root)
    return root


@pytest.fixture()
def seeded_terraform_rule(db: Session) -> Rule:
    rule = db.exec(select(Rule).where(Rule.domain == RuleDomain.iac_terraform)).first()
    assert rule is not None
    return rule


@pytest.fixture()
def completed_scan(db: Session, terraform_root: TerraformRoot) -> TerraformScan:
    scan = TerraformScan(
        terraform_root_id=terraform_root.id,
        status=ScanStatus.completed,
        triggered_by=AnalysisTrigger.manual,
        score=72.0,
        grade="B",
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


# ─── POST /terraform-roots/ ────────────────────────────────────────────────────


def test_create_terraform_root(
    client: TestClient, superuser_token_headers: dict[str, str], repo: Repository
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/terraform-roots/",
        headers=superuser_token_headers,
        json={"repo_id": str(repo.id), "root_path": "infra/prod"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["root_path"] == "infra/prod"
    assert body["repo_id"] == str(repo.id)
    assert body["enabled"] is True


def test_create_terraform_root_normalizes_slashes(
    client: TestClient, superuser_token_headers: dict[str, str], repo: Repository
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/terraform-roots/",
        headers=superuser_token_headers,
        json={"repo_id": str(repo.id), "root_path": "/infra/prod/"},
    )
    assert response.status_code == 201
    assert response.json()["root_path"] == "infra/prod"


def test_create_terraform_root_rejects_empty_path(
    client: TestClient, superuser_token_headers: dict[str, str], repo: Repository
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/terraform-roots/",
        headers=superuser_token_headers,
        json={"repo_id": str(repo.id), "root_path": "///"},
    )
    assert response.status_code == 422


def test_create_terraform_root_duplicate_conflicts(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    terraform_root: TerraformRoot,
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/terraform-roots/",
        headers=superuser_token_headers,
        json={"repo_id": str(repo.id), "root_path": terraform_root.root_path},
    )
    assert response.status_code == 409


# ─── GET /terraform-roots/ ──────────────────────────────────────────────────────


def test_list_terraform_roots(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    terraform_root: TerraformRoot,
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/terraform-roots/",
        headers=superuser_token_headers,
        params={"repo_id": str(repo.id)},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(terraform_root.id)


def test_list_terraform_roots_includes_latest_grade(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    terraform_root: TerraformRoot,
    completed_scan: TerraformScan,  # noqa: ARG001
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/terraform-roots/",
        headers=superuser_token_headers,
        params={"repo_id": str(repo.id)},
    )
    body = response.json()
    assert body[0]["latest_score"] == 72.0
    assert body[0]["latest_grade"] == "B"


# ─── PATCH /terraform-roots/{id}/toggle ────────────────────────────────────────


def test_toggle_terraform_root(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    terraform_root: TerraformRoot,
) -> None:
    response = client.patch(
        f"{settings.API_V1_STR}/terraform-roots/{terraform_root.id}/toggle",
        headers=superuser_token_headers,
        params={"enabled": "false"},
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False


# ─── DELETE /terraform-roots/{id} ───────────────────────────────────────────────


def test_delete_terraform_root_cascades_scans(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    terraform_root: TerraformRoot,
    completed_scan: TerraformScan,
) -> None:
    root_id = terraform_root.id
    scan_id = completed_scan.id
    response = client.delete(
        f"{settings.API_V1_STR}/terraform-roots/{root_id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 204
    # A plain select (not db.get()) avoids ObjectDeletedError when refreshing
    # an already-loaded, strongly-referenced identity-map entry for a row
    # another session just deleted.
    assert (
        db.exec(select(TerraformRoot).where(TerraformRoot.id == root_id)).first()
        is None
    )
    assert (
        db.exec(select(TerraformScan).where(TerraformScan.id == scan_id)).first()
        is None
    )


# ─── POST /terraform-roots/{id}/scan ────────────────────────────────────────────


def test_trigger_terraform_scan(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    terraform_root: TerraformRoot,
) -> None:
    with patch(
        "app.workers.tasks.terraform_analysis.run_terraform_scan.delay"
    ) as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/terraform-roots/{terraform_root.id}/scan",
            headers=superuser_token_headers,
        )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    mock_delay.assert_called_once()
    assert mock_delay.call_args.kwargs["terraform_root_id"] == str(terraform_root.id)


def test_trigger_terraform_scan_disabled_root_rejected(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    terraform_root: TerraformRoot,
) -> None:
    terraform_root.enabled = False
    db.add(terraform_root)
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/terraform-roots/{terraform_root.id}/scan",
        headers=superuser_token_headers,
    )
    assert response.status_code == 403


# ─── GET /terraform-roots/{id}/scans ────────────────────────────────────────────


def test_list_terraform_scans(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    terraform_root: TerraformRoot,
    completed_scan: TerraformScan,
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/terraform-roots/{terraform_root.id}/scans",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(completed_scan.id)
    assert body[0]["grade"] == "B"


# ─── GET /terraform-roots/{id}/findings ─────────────────────────────────────────


def test_list_terraform_findings_excludes_resolved_by_default(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    terraform_root: TerraformRoot,
    completed_scan: TerraformScan,
    seeded_terraform_rule: Rule,
) -> None:
    from datetime import datetime, timezone

    open_finding = TerraformFinding(
        scan_id=completed_scan.id,
        terraform_root_id=terraform_root.id,
        rule_id=seeded_terraform_rule.id,
        resource_address="aws_s3_bucket.data",
        file_path="main.tf",
        fingerprint=uuid.uuid4().hex[:16],
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        message="open finding",
    )
    resolved_finding = TerraformFinding(
        scan_id=completed_scan.id,
        terraform_root_id=terraform_root.id,
        rule_id=seeded_terraform_rule.id,
        resource_address="aws_s3_bucket.other",
        file_path="main.tf",
        fingerprint=uuid.uuid4().hex[:16],
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        message="resolved finding",
        resolved_at=datetime.now(timezone.utc),
    )
    db.add(open_finding)
    db.add(resolved_finding)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/terraform-roots/{terraform_root.id}/findings",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["message"] == "open finding"
    assert body[0]["rule_slug"] == seeded_terraform_rule.slug


def test_list_terraform_findings_include_resolved(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    terraform_root: TerraformRoot,
    completed_scan: TerraformScan,
    seeded_terraform_rule: Rule,
) -> None:
    from datetime import datetime, timezone

    resolved_finding = TerraformFinding(
        scan_id=completed_scan.id,
        terraform_root_id=terraform_root.id,
        rule_id=seeded_terraform_rule.id,
        resource_address="aws_s3_bucket.other",
        file_path="main.tf",
        fingerprint=uuid.uuid4().hex[:16],
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        message="resolved finding",
        resolved_at=datetime.now(timezone.utc),
    )
    db.add(resolved_finding)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/terraform-roots/{terraform_root.id}/findings",
        headers=superuser_token_headers,
        params={"include_resolved": "true"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1
