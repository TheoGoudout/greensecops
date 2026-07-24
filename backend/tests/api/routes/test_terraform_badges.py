"""Tests for the /api/v1/badges/terraform/{root_id} endpoints."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import (
    AnalysisTrigger,
    Organization,
    Repository,
    ScanStatus,
    TerraformRoot,
    TerraformScan,
    UserTier,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"tf-badges-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture()
def repo(db: Session, org: Organization) -> Repository:
    suffix = uuid.uuid4().hex[:8]
    repository = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"tfbadgesowner-{suffix}/repo-{suffix}",
        installation_id=21112,
        default_branch="main",
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def private_repo(db: Session, org: Organization) -> Repository:
    suffix = uuid.uuid4().hex[:8]
    repository = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"tfprivowner-{suffix}/repo-{suffix}",
        installation_id=21113,
        default_branch="main",
        is_private=True,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def root(db: Session, repo: Repository) -> TerraformRoot:
    tf_root = TerraformRoot(repo_id=repo.id, root_path="envs/prod")
    db.add(tf_root)
    db.commit()
    db.refresh(tf_root)
    return tf_root


@pytest.fixture()
def private_root(db: Session, private_repo: Repository) -> TerraformRoot:
    tf_root = TerraformRoot(repo_id=private_repo.id, root_path="envs/prod")
    db.add(tf_root)
    db.commit()
    db.refresh(tf_root)
    return tf_root


def _add_completed_scan(db: Session, root: TerraformRoot, grade: str) -> None:
    db.add(
        TerraformScan(
            terraform_root_id=root.id,
            status=ScanStatus.completed,
            triggered_by=AnalysisTrigger.manual,
            score=92.0,
            grade=grade,
        )
    )
    db.commit()


# ─── SVG badge ────────────────────────────────────────────────────────────────


def test_svg_badge_unknown_root_returns_unknown(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_STR}/badges/terraform/{uuid.uuid4()}.svg")

    assert response.status_code == 200
    assert "image/svg+xml" in response.headers.get("content-type", "")
    assert b"?" in response.content


def test_svg_badge_known_root_no_scan(client: TestClient, root: TerraformRoot) -> None:
    response = client.get(f"{settings.API_V1_STR}/badges/terraform/{root.id}.svg")

    assert response.status_code == 200
    assert b"?" in response.content


def test_svg_badge_known_root_with_grade(
    client: TestClient, db: Session, root: TerraformRoot
) -> None:
    _add_completed_scan(db, root, "A+")

    response = client.get(f"{settings.API_V1_STR}/badges/terraform/{root.id}.svg")

    assert response.status_code == 200
    assert b"A+" in response.content


# ─── JSON badge ───────────────────────────────────────────────────────────────


def test_json_badge_unknown_root(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_STR}/badges/terraform/{uuid.uuid4()}.json")

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "not configured"


def test_json_badge_pending(client: TestClient, root: TerraformRoot) -> None:
    response = client.get(f"{settings.API_V1_STR}/badges/terraform/{root.id}.json")

    assert response.status_code == 200
    assert response.json()["message"] == "pending"


def test_json_badge_with_grade(
    client: TestClient, db: Session, root: TerraformRoot
) -> None:
    _add_completed_scan(db, root, "A+")

    response = client.get(f"{settings.API_V1_STR}/badges/terraform/{root.id}.json")

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "A+"
    assert body.get("cacheSeconds") == 300


# ─── Private-repo signature enforcement ───────────────────────────────────────


def test_private_svg_without_sig_returns_unknown(
    client: TestClient, db: Session, private_root: TerraformRoot
) -> None:
    _add_completed_scan(db, private_root, "A+")

    response = client.get(
        f"{settings.API_V1_STR}/badges/terraform/{private_root.id}.svg"
    )

    assert response.status_code == 200
    assert b"A+" not in response.content
    assert b"?" in response.content


def test_private_svg_with_valid_sig_returns_grade(
    client: TestClient, db: Session, private_root: TerraformRoot
) -> None:
    from app.services.badge_signing import sign_terraform_root_badge

    _add_completed_scan(db, private_root, "A+")
    sig = sign_terraform_root_badge(str(private_root.id))

    response = client.get(
        f"{settings.API_V1_STR}/badges/terraform/{private_root.id}.svg",
        params={"sig": sig},
    )

    assert response.status_code == 200
    assert b"A+" in response.content


def test_private_svg_with_wrong_sig_returns_unknown(
    client: TestClient, db: Session, private_root: TerraformRoot
) -> None:
    _add_completed_scan(db, private_root, "A+")

    response = client.get(
        f"{settings.API_V1_STR}/badges/terraform/{private_root.id}.svg",
        params={"sig": "deadbeef"},
    )

    assert response.status_code == 200
    assert b"A+" not in response.content


def test_private_json_without_sig_not_configured(
    client: TestClient, db: Session, private_root: TerraformRoot
) -> None:
    _add_completed_scan(db, private_root, "A+")

    response = client.get(
        f"{settings.API_V1_STR}/badges/terraform/{private_root.id}.json"
    )

    assert response.status_code == 200
    assert response.json()["message"] == "not configured"


def test_private_json_with_valid_sig_returns_grade(
    client: TestClient, db: Session, private_root: TerraformRoot
) -> None:
    from app.services.badge_signing import sign_terraform_root_badge

    _add_completed_scan(db, private_root, "A+")
    sig = sign_terraform_root_badge(str(private_root.id))

    response = client.get(
        f"{settings.API_V1_STR}/badges/terraform/{private_root.id}.json",
        params={"sig": sig},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "A+"
