"""The Stripe gateway: configuration guards and price↔tier mapping.

The point of funnelling every outbound call through one module is that an
unconfigured deployment fails in exactly one recognisable way. These tests pin
that, and pin the price mapping being derived from the catalog rather than a
hand-written table that could fall behind it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models import UserTier
from app.services.billing import stripe_gateway

# ─── Configuration guard ─────────────────────────────────────────────────────


def test_is_configured_follows_the_secret_key() -> None:
    with patch.object(settings, "STRIPE_SECRET_KEY", None):
        assert stripe_gateway.is_configured() is False
    with patch.object(settings, "STRIPE_SECRET_KEY", "sk_test_x"):
        assert stripe_gateway.is_configured() is True


def test_checkout_without_credentials_raises_a_clear_503() -> None:
    """Self-hosted installs get a sentence, not an SDK stack trace."""
    with (
        patch.object(settings, "STRIPE_SECRET_KEY", None),
        pytest.raises(HTTPException) as exc,
    ):
        stripe_gateway.create_checkout_session(
            tier=UserTier.pro,
            customer_id=None,
            customer_email="a@example.com",
            client_reference_id="x",
            success_url="https://app/ok",
            cancel_url="https://app/no",
        )
    assert exc.value.status_code == 503
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "stripe_not_configured"
    assert "STRIPE_SECRET_KEY" in detail["message"]


def test_portal_without_credentials_raises_a_clear_503() -> None:
    with (
        patch.object(settings, "STRIPE_SECRET_KEY", None),
        pytest.raises(HTTPException) as exc,
    ):
        stripe_gateway.create_portal_session(
            customer_id="cus_x", return_url="https://app/billing"
        )
    assert exc.value.status_code == 503


def test_checkout_for_a_tier_with_no_price_is_refused() -> None:
    """Free and open_source are never sold through Checkout."""
    with (
        patch.object(settings, "STRIPE_SECRET_KEY", "sk_test_x"),
        pytest.raises(HTTPException) as exc,
    ):
        stripe_gateway.create_checkout_session(
            tier=UserTier.free,
            customer_id=None,
            customer_email="a@example.com",
            client_reference_id="x",
            success_url="https://app/ok",
            cancel_url="https://app/no",
        )
    assert exc.value.status_code == 503


# ─── Price ↔ tier mapping ────────────────────────────────────────────────────


def test_price_id_comes_from_the_catalog() -> None:
    with (
        patch.object(settings, "STRIPE_PRICE_PRO", "price_pro_123"),
        patch.object(settings, "STRIPE_PRICE_STARTER", "price_starter_123"),
    ):
        assert stripe_gateway.price_id_for(UserTier.pro) == "price_pro_123"
        assert stripe_gateway.price_id_for(UserTier.starter) == "price_starter_123"
    # Not purchasable, so no price at all.
    assert stripe_gateway.price_id_for(UserTier.free) is None
    assert stripe_gateway.price_id_for(UserTier.open_source) is None


def test_tier_for_price_reverses_the_mapping() -> None:
    """Built from the catalog, so adding a plan cannot leave the webhook blind."""
    with patch.object(settings, "STRIPE_PRICE_ULTIMATE", "price_ult_9"):
        assert stripe_gateway.tier_for_price("price_ult_9") == UserTier.ultimate


def test_an_unknown_price_maps_to_nothing() -> None:
    assert stripe_gateway.tier_for_price("price_who_knows") is None
    assert stripe_gateway.tier_for_price("") is None


def test_an_unconfigured_price_does_not_match_by_accident() -> None:
    """A ``None`` setting must not make ``None`` a valid lookup key."""
    with patch.object(settings, "STRIPE_PRICE_PRO", None):
        assert stripe_gateway.tier_for_price("") is None


# ─── Outbound calls ──────────────────────────────────────────────────────────


def test_checkout_passes_the_client_reference_through() -> None:
    """That id is how the webhook matches the result back to an account."""
    fake = MagicMock()
    fake.checkout.Session.create.return_value = {"url": "https://checkout/x"}
    with (
        patch.object(settings, "STRIPE_SECRET_KEY", "sk_test_x"),
        patch.object(settings, "STRIPE_PRICE_PRO", "price_pro"),
        patch.object(stripe_gateway, "_client", return_value=fake),
    ):
        url = stripe_gateway.create_checkout_session(
            tier=UserTier.pro,
            customer_id=None,
            customer_email="a@example.com",
            client_reference_id="sub-uuid",
            success_url="https://app/ok",
            cancel_url="https://app/no",
        )
    assert url == "https://checkout/x"
    params = fake.checkout.Session.create.call_args.kwargs
    assert params["client_reference_id"] == "sub-uuid"
    assert params["mode"] == "subscription"
    assert params["line_items"] == [{"price": "price_pro", "quantity": 1}]
    # No customer id yet, so Stripe is given the email to create one from.
    assert params["customer_email"] == "a@example.com"
    assert "customer" not in params


def test_checkout_reuses_an_existing_customer() -> None:
    """One payment profile per account, not a new one per checkout attempt."""
    fake = MagicMock()
    fake.checkout.Session.create.return_value = {"url": "https://checkout/y"}
    with (
        patch.object(settings, "STRIPE_SECRET_KEY", "sk_test_x"),
        patch.object(settings, "STRIPE_PRICE_PRO", "price_pro"),
        patch.object(stripe_gateway, "_client", return_value=fake),
    ):
        stripe_gateway.create_checkout_session(
            tier=UserTier.pro,
            customer_id="cus_existing",
            customer_email="a@example.com",
            client_reference_id="sub-uuid",
            success_url="https://app/ok",
            cancel_url="https://app/no",
        )
    params = fake.checkout.Session.create.call_args.kwargs
    assert params["customer"] == "cus_existing"
    assert "customer_email" not in params


def test_portal_session_targets_the_customer() -> None:
    fake = MagicMock()
    fake.billing_portal.Session.create.return_value = {"url": "https://portal/z"}
    with (
        patch.object(settings, "STRIPE_SECRET_KEY", "sk_test_x"),
        patch.object(stripe_gateway, "_client", return_value=fake),
    ):
        url = stripe_gateway.create_portal_session(
            customer_id="cus_1", return_url="https://app/billing"
        )
    assert url == "https://portal/z"
    params = fake.billing_portal.Session.create.call_args.kwargs
    assert params["customer"] == "cus_1"
    assert params["return_url"] == "https://app/billing"


# ─── Webhook parsing ─────────────────────────────────────────────────────────


def test_webhook_parsing_requires_both_secrets() -> None:
    with (
        patch.object(settings, "STRIPE_WEBHOOK_SECRET", None),
        pytest.raises(HTTPException) as exc,
    ):
        stripe_gateway.parse_webhook_event(b"{}", "sig")
    assert exc.value.status_code == 503


def test_a_bad_signature_is_a_400_not_a_500() -> None:
    """A tampered payload is the sender's fault, and Stripe must not retry it."""
    with (
        patch.object(settings, "STRIPE_SECRET_KEY", "sk_test_x"),
        patch.object(settings, "STRIPE_WEBHOOK_SECRET", "whsec_x"),
        pytest.raises(HTTPException) as exc,
    ):
        stripe_gateway.parse_webhook_event(b'{"a":1}', "t=1,v1=nonsense")
    assert exc.value.status_code == 400
