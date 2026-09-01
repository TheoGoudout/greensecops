"""The Stripe gateway: configuration guards and price↔tier mapping.

The point of funnelling every outbound call through one module is that an
unconfigured deployment fails in exactly one recognisable way. These tests pin
that, and pin the price mapping being derived from the catalog rather than a
hand-written table that could fall behind it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import stripe
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
        checkout = stripe_gateway.create_checkout_session(
            tier=UserTier.pro,
            customer_id=None,
            customer_email="a@example.com",
            client_reference_id="sub-uuid",
            success_url="https://app/ok",
            cancel_url="https://app/no",
        )
    assert checkout.url == "https://checkout/x"
    assert checkout.customer_id_rejected is False
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


def test_checkout_retries_without_a_customer_stripe_says_is_gone() -> None:
    """A customer deleted in the dashboard must not block every future purchase.

    Stripe refuses the session outright when the `customer` we send no longer
    exists, which left the account unable to buy any plan at all.
    """
    fake = MagicMock()
    fake.checkout.Session.create.side_effect = [
        stripe.InvalidRequestError(
            "No such customer: cus_gone", param="customer", code="resource_missing"
        ),
        {"url": "https://checkout/recovered"},
    ]
    with (
        patch.object(settings, "STRIPE_SECRET_KEY", "sk_test_x"),
        patch.object(settings, "STRIPE_PRICE_PRO", "price_pro"),
        patch.object(stripe_gateway, "_client", return_value=fake),
    ):
        checkout = stripe_gateway.create_checkout_session(
            tier=UserTier.pro,
            customer_id="cus_gone",
            customer_email="a@example.com",
            client_reference_id="sub-uuid",
            success_url="https://app/ok",
            cancel_url="https://app/no",
        )

    assert checkout.url == "https://checkout/recovered"
    # Reported so the caller can clear the dead id rather than rediscovering it.
    assert checkout.customer_id_rejected is True
    retry = fake.checkout.Session.create.call_args.kwargs
    assert "customer" not in retry
    # The email takes its place, so Stripe mints a fresh customer.
    assert retry["customer_email"] == "a@example.com"


def test_checkout_does_not_retry_on_an_unrelated_stripe_error() -> None:
    """Only a missing *customer* is recoverable; a bad price is a real error."""
    fake = MagicMock()
    fake.checkout.Session.create.side_effect = stripe.InvalidRequestError(
        "No such price: price_pro", param="line_items[0][price]", code="resource_missing"
    )
    with (
        patch.object(settings, "STRIPE_SECRET_KEY", "sk_test_x"),
        patch.object(settings, "STRIPE_PRICE_PRO", "price_pro"),
        patch.object(stripe_gateway, "_client", return_value=fake),
        pytest.raises(stripe.InvalidRequestError),
    ):
        stripe_gateway.create_checkout_session(
            tier=UserTier.pro,
            customer_id="cus_ok",
            customer_email="a@example.com",
            client_reference_id="sub-uuid",
            success_url="https://app/ok",
            cancel_url="https://app/no",
        )
    assert fake.checkout.Session.create.call_count == 1


# ─── Changing an existing subscription's plan ────────────────────────────────


def _stripe_client(subscription: dict) -> MagicMock:
    client = MagicMock()
    client.Subscription.retrieve.return_value = subscription
    return client


SUBSCRIPTION = {
    "id": "sub_123",
    "items": {"data": [{"id": "si_1", "price": {"id": "price_starter"}}]},
}

# One period, ending in the middle of 2026 — the moment a deferred change lands.
PERIOD_END = 1_780_000_000
SCHEDULE = {
    "id": "sub_sched_1",
    "phases": [
        {
            "items": [{"price": "price_pro"}],
            "start_date": 1_777_000_000,
            "end_date": PERIOD_END,
        }
    ],
}


def _prices() -> object:
    return patch.multiple(
        settings,
        STRIPE_SECRET_KEY="sk_test_x",
        STRIPE_PRICE_STARTER="price_starter",
        STRIPE_PRICE_PRO="price_pro",
    )


def test_an_upgrade_swaps_the_price_and_invoices_the_difference() -> None:
    """The point of the whole exercise.

    ``always_invoice`` credits the unused remainder of the plan being left and
    bills only the balance, so the first payment on the new plan is the
    difference rather than a second full price.
    """
    client = _stripe_client(SUBSCRIPTION)
    with _prices(), patch.object(stripe_gateway, "_client", return_value=client):
        change = stripe_gateway.change_subscription_plan(
            subscription_id="sub_123", tier=UserTier.pro, immediate=True
        )

    client.Subscription.modify.assert_called_once_with(
        "sub_123",
        items=[{"id": "si_1", "price": "price_pro"}],
        proration_behavior="always_invoice",
    )
    # No second subscription was opened, which is the bug this replaces.
    client.checkout.Session.create.assert_not_called()
    assert change.tier == UserTier.pro
    assert change.is_immediate


def test_a_downgrade_starts_at_the_renewal_and_not_before() -> None:
    """A downgrade taking effect now would forfeit time already paid for."""
    client = _stripe_client(SUBSCRIPTION)
    client.SubscriptionSchedule.create.return_value = SCHEDULE
    with _prices(), patch.object(stripe_gateway, "_client", return_value=client):
        change = stripe_gateway.change_subscription_plan(
            subscription_id="sub_123", tier=UserTier.starter, immediate=False
        )

    # Nothing about the live subscription changes; only what follows it.
    client.Subscription.modify.assert_not_called()
    phases = client.SubscriptionSchedule.modify.call_args.kwargs["phases"]
    # The plan already paid for runs to the end of the period it was bought for.
    assert phases[0]["items"] == [{"price": "price_pro", "quantity": 1}]
    assert phases[0]["end_date"] == PERIOD_END
    assert phases[1]["items"] == [{"price": "price_starter", "quantity": 1}]
    assert (
        client.SubscriptionSchedule.modify.call_args.kwargs["end_behavior"] == "release"
    )
    assert change.tier == UserTier.starter
    assert not change.is_immediate
    assert change.effective_at is not None
    assert change.effective_at.timestamp() == PERIOD_END


def test_a_second_downgrade_edits_the_schedule_already_standing() -> None:
    """Stripe refuses a second schedule, and the user would be stuck."""
    client = _stripe_client({**SUBSCRIPTION, "schedule": "sub_sched_1"})
    client.SubscriptionSchedule.retrieve.return_value = SCHEDULE
    with _prices(), patch.object(stripe_gateway, "_client", return_value=client):
        stripe_gateway.change_subscription_plan(
            subscription_id="sub_123", tier=UserTier.starter, immediate=False
        )

    client.SubscriptionSchedule.create.assert_not_called()
    client.SubscriptionSchedule.retrieve.assert_called_once_with("sub_sched_1")
    client.SubscriptionSchedule.modify.assert_called_once()


def test_an_expanded_schedule_object_is_accepted_too() -> None:
    """Stripe returns the schedule as an id or an object depending on expansion."""
    client = _stripe_client({**SUBSCRIPTION, "schedule": {"id": "sub_sched_1"}})
    client.SubscriptionSchedule.retrieve.return_value = SCHEDULE
    with _prices(), patch.object(stripe_gateway, "_client", return_value=client):
        stripe_gateway.change_subscription_plan(
            subscription_id="sub_123", tier=UserTier.starter, immediate=False
        )

    client.SubscriptionSchedule.retrieve.assert_called_once_with("sub_sched_1")


def test_changing_to_an_unpurchasable_plan_raises_a_clear_503() -> None:
    with (
        patch.object(settings, "STRIPE_SECRET_KEY", "sk_test_x"),
        pytest.raises(HTTPException) as exc,
    ):
        stripe_gateway.change_subscription_plan(
            subscription_id="sub_123", tier=UserTier.free, immediate=True
        )
    assert exc.value.status_code == 503
