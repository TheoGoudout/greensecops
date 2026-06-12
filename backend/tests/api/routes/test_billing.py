"""Tests for the /api/v1/billing/ endpoints."""

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings

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
