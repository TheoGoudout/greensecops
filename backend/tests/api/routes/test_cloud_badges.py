"""Tests for the /api/v1/badges/cloud/{account_id} endpoints."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import (
    CloudAccount,
    CloudScan,
    Organization,
    ScanStatus,
    ScanTrigger,
    UserTier,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"cloud-badges-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture()
def account(db: Session, org: Organization) -> CloudAccount:
    cloud_account = CloudAccount(
        org_id=org.id,
        display_name="prod",
        external_id=uuid.uuid4().hex,
    )
    db.add(cloud_account)
    db.commit()
    db.refresh(cloud_account)
    return cloud_account


def _add_completed_scan(db: Session, account: CloudAccount, grade: str) -> None:
    db.add(
        CloudScan(
            cloud_account_id=account.id,
            status=ScanStatus.completed,
            triggered_by=ScanTrigger.manual,
            score=92.0,
            grade=grade,
        )
    )
    db.commit()


# ─── SVG badge ────────────────────────────────────────────────────────────────


def test_svg_badge_unknown_account_returns_unknown(client: TestClient) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/badges/cloud/{uuid.uuid4()}.svg"
    )

    assert response.status_code == 200
    assert "image/svg+xml" in response.headers.get("content-type", "")
    assert b"?" in response.content


def test_svg_badge_without_sig_returns_unknown(
    client: TestClient, db: Session, account: CloudAccount
) -> None:
    """A cloud account has no public counterpart — a sig is always required."""
    _add_completed_scan(db, account, "A+")

    response = client.get(
        f"{settings.API_V1_STR}/badges/cloud/{account.id}.svg"
    )

    assert response.status_code == 200
    assert b"A+" not in response.content
    assert b"?" in response.content


def test_svg_badge_with_valid_sig_returns_grade(
    client: TestClient, db: Session, account: CloudAccount
) -> None:
    from app.services.badge_signing import sign_badge

    _add_completed_scan(db, account, "A+")
    sig = sign_badge(str(account.id))

    response = client.get(
        f"{settings.API_V1_STR}/badges/cloud/{account.id}.svg",
        params={"sig": sig},
    )

    assert response.status_code == 200
    assert b"A+" in response.content


def test_svg_badge_with_wrong_sig_returns_unknown(
    client: TestClient, db: Session, account: CloudAccount
) -> None:
    _add_completed_scan(db, account, "A+")

    response = client.get(
        f"{settings.API_V1_STR}/badges/cloud/{account.id}.svg",
        params={"sig": "deadbeef"},
    )

    assert response.status_code == 200
    assert b"A+" not in response.content


# ─── JSON badge ───────────────────────────────────────────────────────────────


def test_json_badge_unknown_account(client: TestClient) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/badges/cloud/{uuid.uuid4()}.json"
    )

    assert response.status_code == 200
    assert response.json()["message"] == "not configured"


def test_json_badge_without_sig_not_configured(
    client: TestClient, db: Session, account: CloudAccount
) -> None:
    _add_completed_scan(db, account, "A+")

    response = client.get(
        f"{settings.API_V1_STR}/badges/cloud/{account.id}.json"
    )

    assert response.status_code == 200
    assert response.json()["message"] == "not configured"


def test_json_badge_with_valid_sig_returns_grade(
    client: TestClient, db: Session, account: CloudAccount
) -> None:
    from app.services.badge_signing import sign_badge

    _add_completed_scan(db, account, "A+")
    sig = sign_badge(str(account.id))

    response = client.get(
        f"{settings.API_V1_STR}/badges/cloud/{account.id}.json",
        params={"sig": sig},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "A+"
    assert body.get("cacheSeconds") == 300


def test_json_badge_pending_with_valid_sig(
    client: TestClient, account: CloudAccount
) -> None:
    from app.services.badge_signing import sign_badge

    sig = sign_badge(str(account.id))

    response = client.get(
        f"{settings.API_V1_STR}/badges/cloud/{account.id}.json",
        params={"sig": sig},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "pending"


# ─── List endpoint carries the signature ───────────────────────────────────────


def test_list_cloud_accounts_includes_badge_sig(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    org: Organization,
    account: CloudAccount,
) -> None:
    from app.services.badge_signing import sign_badge

    response = client.get(
        f"{settings.API_V1_STR}/cloud/accounts",
        headers=superuser_token_headers,
        params={"org_id": str(org.id)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body[0]["badge_sig"] == sign_badge(str(account.id))
