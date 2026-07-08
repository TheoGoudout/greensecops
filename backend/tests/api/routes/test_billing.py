"""Tests for the /api/v1/billing/ endpoints."""

import uuid
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.routes import billing
from app.core.config import settings
from app.models import User, UserTier


def test_enforce_quota_superuser_exempt(db: Session) -> None:
    user = User(
        email=f"su-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        is_superuser=True,
        tier=UserTier.free,
    )
    # Superusers bypass quotas even with a zero limit.
    with patch.dict(billing._TIER_LIMITS, {UserTier.free: {"fixes": 0}}):
        billing.enforce_quota(db, user, "fixes")  # must not raise


def test_enforce_quota_blocks_at_limit(db: Session) -> None:
    user = User(
        email=f"nu-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        is_superuser=False,
        tier=UserTier.free,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    # Limit of 0 → any usage (including zero) is at/over the limit.
    with patch.dict(billing._TIER_LIMITS, {UserTier.free: {"fixes": 0}}):
        with pytest.raises(HTTPException) as exc:
            billing.enforce_quota(db, user, "fixes")
    assert exc.value.status_code == 402


def test_enforce_quota_replacing_does_not_count(db: Session) -> None:
    user = User(
        email=f"nu-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        is_superuser=False,
        tier=UserTier.free,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    with (
        patch.dict(billing._TIER_LIMITS, {UserTier.free: {"fixes": 5}}),
        patch.object(billing, "_usage_for_user", return_value=(0, 5, [])),
    ):
        # Regenerating all 5 existing fixes keeps the total at the limit → OK.
        billing.enforce_quota(db, user, "fixes", requested=5, replacing=5)
        # One net-new fix on top of the replaced ones exceeds the limit.
        with pytest.raises(HTTPException) as exc:
            billing.enforce_quota(db, user, "fixes", requested=6, replacing=5)
    assert exc.value.status_code == 402


def test_enforce_quota_default_still_blocks_at_limit(db: Session) -> None:
    user = User(
        email=f"nu-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        is_superuser=False,
        tier=UserTier.free,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    with (
        patch.dict(billing._TIER_LIMITS, {UserTier.free: {"fixes": 5}}),
        patch.object(billing, "_usage_for_user", return_value=(0, 5, [])),
        pytest.raises(HTTPException) as exc,
    ):
        billing.enforce_quota(db, user, "fixes")
    assert exc.value.status_code == 402


def test_enforce_quota_unlimited_tier(db: Session) -> None:
    user = User(
        email=f"un-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        is_superuser=False,
        tier=UserTier.ultimate,
    )
    db.add(user)
    db.commit()
    # ultimate has None (unlimited) for fixes → never blocks.
    billing.enforce_quota(db, user, "fixes")  # must not raise


# ─── GET /billing/subscription ───────────────────────────────────────────────


def test_get_subscription_creates_if_not_exists(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    # Act — first call creates the subscription
    response = client.get(
        f"{settings.API_V1_STR}/billing/subscription",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert "id" in body
    assert body["tier"] == "free"
    assert body["analyses_used"] == 0
    assert body["fixes_used"] == 0


def test_get_subscription_re_fetch_returns_same(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    # Act — call twice
    first = client.get(
        f"{settings.API_V1_STR}/billing/subscription",
        headers=superuser_token_headers,
    )
    second = client.get(
        f"{settings.API_V1_STR}/billing/subscription",
        headers=superuser_token_headers,
    )

    # Assert — same id returned both times
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


# ─── GET /billing/limits ──────────────────────────────────────────────────────


def test_get_tier_limits_returns_tier_and_limits(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/billing/limits",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert "tier" in body
    assert "limits" in body
    limits = body["limits"]
    assert "analyses" in limits
    assert "fixes" in limits
    assert "repos" in limits


# ─── POST /billing/webhook/stripe ────────────────────────────────────────────


def test_stripe_webhook_returns_503_when_not_configured(
    client: TestClient,
) -> None:
    # Act — no authentication required for webhook endpoints;
    # Stripe is not configured in the test environment so the endpoint
    # should return 503 Service Unavailable.
    response = client.post(
        f"{settings.API_V1_STR}/billing/webhook/stripe",
        json={},
    )

    # Assert
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]
