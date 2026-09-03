"""The Stripe gateway: configuration guards and price↔tier mapping.

The point of funnelling every outbound call through one module is that an
unconfigured deployment fails in exactly one recognisable way. These tests pin
that, and pin the price mapping being derived from the catalog rather than a
hand-written table that could fall behind it.
"""

from __future__ import annotations

from collections.abc import Iterator
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
        "No such price: price_pro",
        param="line_items[0][price]",
        code="resource_missing",
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

SUBSCRIPTION = {
    "id": "sub_123",
    "customer": "cus_123",
    "items": {"data": [{"id": "si_1", "price": {"id": "price_starter"}}]},
}

# Two plans on one Stripe product and a third on its own, so the grouping is
# exercised rather than assumed — and the third comes back expanded, which is
# the other shape Stripe answers `price.product` with.
PRODUCT_OF = {
    "price_starter": "prod_plans",
    "price_pro": "prod_plans",
    "price_ultimate": {"id": "prod_ultimate"},
}
CATALOG_PRODUCTS = [
    {"product": "prod_plans", "prices": ["price_starter", "price_pro"]},
    {"product": "prod_ultimate", "prices": ["price_ultimate"]},
]


@pytest.fixture(autouse=True)
def _forget_resolved_configurations() -> Iterator[None]:
    """The configuration id is cached per price set; tests change prices."""
    stripe_gateway._CONFIGURATION_CACHE.clear()
    yield
    stripe_gateway._CONFIGURATION_CACHE.clear()


def _stripe_client(
    subscription: dict | None = None, *, configurations: list[dict] | None = None
) -> MagicMock:
    client = MagicMock()
    client.Subscription.retrieve.return_value = subscription or SUBSCRIPTION
    client.Price.retrieve.side_effect = lambda price_id: {
        "id": price_id,
        "product": PRODUCT_OF[price_id],
    }
    client.billing_portal.Configuration.list.return_value = {
        "data": configurations or []
    }
    client.billing_portal.Configuration.create.return_value = {"id": "bpc_new"}
    client.billing_portal.Configuration.modify.return_value = {"id": "bpc_existing"}
    client.billing_portal.Session.create.return_value = {
        "url": "https://portal/confirm"
    }
    return client


def _configuration(prices: list[str], *, mine: bool = True) -> dict:
    return {
        "id": "bpc_existing",
        "metadata": {"greensecops": "plan-changes"} if mine else {"other": "thing"},
        "features": {
            "subscription_update": {
                "products": [{"product": "prod_plans", "prices": prices}]
            }
        },
    }


def _prices() -> object:
    return patch.multiple(
        settings,
        STRIPE_SECRET_KEY="sk_test_x",
        STRIPE_PRICE_STARTER="price_starter",
        STRIPE_PRICE_PRO="price_pro",
        STRIPE_PRICE_ULTIMATE="price_ultimate",
        STRIPE_PORTAL_CONFIGURATION_ID=None,
    )


def test_a_plan_change_is_confirmed_on_stripe_rather_than_charged_here() -> None:
    """The point of the whole exercise.

    Nothing is modified from this end: the customer is handed a Stripe page
    naming the price change, and only their confirmation there moves any money.
    """
    client = _stripe_client()
    with _prices(), patch.object(stripe_gateway, "_client", return_value=client):
        url = stripe_gateway.create_plan_change_session(
            subscription_id="sub_123",
            customer_id="cus_123",
            tier=UserTier.pro,
            return_url="https://app/billing",
        )

    assert url == "https://portal/confirm"
    params = client.billing_portal.Session.create.call_args.kwargs
    assert params["customer"] == "cus_123"
    assert params["configuration"] == "bpc_new"
    flow = params["flow_data"]
    assert flow["type"] == "subscription_update_confirm"
    assert flow["subscription_update_confirm"]["subscription"] == "sub_123"
    # The one item the plan lives on, moved to the new price.
    assert flow["subscription_update_confirm"]["items"] == [
        {"id": "si_1", "price": "price_pro", "quantity": 1}
    ]
    assert flow["after_completion"] == {
        "type": "redirect",
        "redirect": {"return_url": "https://app/billing"},
    }
    # Neither of the two ways this used to move money behind the user's back.
    client.Subscription.modify.assert_not_called()
    client.checkout.Session.create.assert_not_called()


def test_a_downgrade_goes_through_the_same_flow() -> None:
    """Direction is the configuration's business, not this module's.

    There is no price comparison here any more: ``schedule_at_period_end``
    below is what defers a cheaper plan to the renewal, so our idea of which
    way a change goes and Stripe's cannot drift apart.
    """
    client = _stripe_client()
    with _prices(), patch.object(stripe_gateway, "_client", return_value=client):
        stripe_gateway.create_plan_change_session(
            subscription_id="sub_123",
            customer_id="cus_123",
            tier=UserTier.starter,
            return_url="https://app/billing",
        )

    flow = client.billing_portal.Session.create.call_args.kwargs["flow_data"]
    assert flow["type"] == "subscription_update_confirm"
    assert flow["subscription_update_confirm"]["items"][0]["price"] == "price_starter"
    client.SubscriptionSchedule.create.assert_not_called()


# ─── The portal configuration ────────────────────────────────────────────────


def test_the_configuration_is_built_from_the_plan_catalog() -> None:
    """Stripe only allows switching to a price the configuration lists.

    Deriving it from the catalog is what stops a plan added to ``core/plans.py``
    from being unsellable through the portal until someone remembers to add it
    in the dashboard as well.
    """
    client = _stripe_client()
    with _prices(), patch.object(stripe_gateway, "_client", return_value=client):
        stripe_gateway.create_plan_change_session(
            subscription_id="sub_123",
            customer_id="cus_123",
            tier=UserTier.pro,
            return_url="https://app/billing",
        )

    created = client.billing_portal.Configuration.create.call_args.kwargs
    assert created["metadata"] == {"greensecops": "plan-changes"}
    update = created["features"]["subscription_update"]
    assert update["enabled"] is True
    assert update["products"] == CATALOG_PRODUCTS
    # The whole billing policy for a plan change, in the three settings Stripe
    # both applies and explains on the confirmation page.
    assert update["proration_behavior"] == "always_invoice"
    assert update["schedule_at_period_end"] == {
        "conditions": [{"type": "decreasing_item_amount"}]
    }
    assert update["trial_update_behavior"] == "continue_trial"
    # The same configuration backs "Manage subscription", so it carries those
    # features too rather than opening an empty portal.
    assert created["features"]["payment_method_update"]["enabled"] is True
    assert created["features"]["subscription_cancel"]["enabled"] is True


def test_a_configuration_already_matching_the_catalog_is_reused() -> None:
    client = _stripe_client(
        configurations=[
            _configuration(["price_starter", "price_pro", "price_ultimate"])
        ]
    )
    with _prices(), patch.object(stripe_gateway, "_client", return_value=client):
        stripe_gateway.create_plan_change_session(
            subscription_id="sub_123",
            customer_id="cus_123",
            tier=UserTier.pro,
            return_url="https://app/billing",
        )

    client.billing_portal.Configuration.create.assert_not_called()
    client.billing_portal.Configuration.modify.assert_not_called()
    # No prices had to be resolved to products either.
    client.Price.retrieve.assert_not_called()
    params = client.billing_portal.Session.create.call_args.kwargs
    assert params["configuration"] == "bpc_existing"


def test_a_configuration_whose_prices_drifted_is_brought_back_in_line() -> None:
    """A price changed in the catalog updates the standing configuration.

    Creating a second one beside it on every price change would leave a trail
    of stale configurations, and no way to tell which is current.
    """
    client = _stripe_client(configurations=[_configuration(["price_starter"])])
    with _prices(), patch.object(stripe_gateway, "_client", return_value=client):
        stripe_gateway.create_plan_change_session(
            subscription_id="sub_123",
            customer_id="cus_123",
            tier=UserTier.pro,
            return_url="https://app/billing",
        )

    client.billing_portal.Configuration.create.assert_not_called()
    modified = client.billing_portal.Configuration.modify.call_args
    assert modified.args == ("bpc_existing",)
    assert modified.kwargs["features"]["subscription_update"]["products"] == (
        CATALOG_PRODUCTS
    )


def test_someone_elses_configuration_is_left_alone() -> None:
    """Only the one this module marked as its own is ever edited."""
    client = _stripe_client(
        configurations=[_configuration(["price_starter", "price_pro"], mine=False)]
    )
    with _prices(), patch.object(stripe_gateway, "_client", return_value=client):
        stripe_gateway.create_plan_change_session(
            subscription_id="sub_123",
            customer_id="cus_123",
            tier=UserTier.pro,
            return_url="https://app/billing",
        )

    client.billing_portal.Configuration.modify.assert_not_called()
    client.billing_portal.Configuration.create.assert_called_once()


def test_a_pinned_configuration_id_skips_provisioning_entirely() -> None:
    """An operator managing the configuration by hand keeps that control."""
    client = _stripe_client()
    with (
        _prices(),
        patch.object(settings, "STRIPE_PORTAL_CONFIGURATION_ID", "bpc_by_hand"),
        patch.object(stripe_gateway, "_client", return_value=client),
    ):
        stripe_gateway.create_plan_change_session(
            subscription_id="sub_123",
            customer_id="cus_123",
            tier=UserTier.pro,
            return_url="https://app/billing",
        )

    client.billing_portal.Configuration.list.assert_not_called()
    client.billing_portal.Configuration.create.assert_not_called()
    params = client.billing_portal.Session.create.call_args.kwargs
    assert params["configuration"] == "bpc_by_hand"


def test_the_configuration_is_resolved_once_per_price_set() -> None:
    """Every plan change would otherwise cost an extra round trip to Stripe."""
    client = _stripe_client()
    with _prices(), patch.object(stripe_gateway, "_client", return_value=client):
        for tier in (UserTier.pro, UserTier.ultimate):
            stripe_gateway.create_plan_change_session(
                subscription_id="sub_123",
                customer_id="cus_123",
                tier=tier,
                return_url="https://app/billing",
            )

    assert client.billing_portal.Configuration.list.call_count == 1
    assert client.billing_portal.Configuration.create.call_count == 1
    assert client.billing_portal.Session.create.call_count == 2


def test_a_deployment_with_no_prices_still_opens_the_portal() -> None:
    """Stripe refuses a configuration that enables switching to nothing.

    Cards and cancellation still work on the account default, which is all a
    deployment with no prices configured could have offered anyway.
    """
    client = _stripe_client()
    with (
        patch.multiple(
            settings,
            STRIPE_SECRET_KEY="sk_test_x",
            STRIPE_PRICE_STARTER=None,
            STRIPE_PRICE_PRO=None,
            STRIPE_PRICE_ULTIMATE=None,
            STRIPE_PORTAL_CONFIGURATION_ID=None,
        ),
        patch.object(stripe_gateway, "_client", return_value=client),
    ):
        url = stripe_gateway.create_portal_session(
            customer_id="cus_123", return_url="https://app/billing"
        )

    assert url == "https://portal/confirm"
    client.billing_portal.Configuration.create.assert_not_called()
    assert "configuration" not in client.billing_portal.Session.create.call_args.kwargs


def test_the_manage_subscription_portal_uses_the_same_configuration() -> None:
    """Otherwise it would open the account default, which may allow nothing."""
    client = _stripe_client()
    with _prices(), patch.object(stripe_gateway, "_client", return_value=client):
        url = stripe_gateway.create_portal_session(
            customer_id="cus_123", return_url="https://app/billing"
        )

    assert url == "https://portal/confirm"
    params = client.billing_portal.Session.create.call_args.kwargs
    assert params["configuration"] == "bpc_new"
    assert "flow_data" not in params


# ─── Leftovers from the old deferred-downgrade path ──────────────────────────


def test_a_subscription_still_driven_by_a_schedule_is_released_and_retried() -> None:
    """Downgrades used to be deferred by a schedule this module created.

    Stripe will not let the portal touch a subscription a schedule is driving,
    which would leave those accounts unable to change plan at all.
    """
    client = _stripe_client({**SUBSCRIPTION, "schedule": "sub_sched_1"})
    client.billing_portal.Session.create.side_effect = [
        stripe.InvalidRequestError(
            "The subscription is managed by a schedule", param="subscription"
        ),
        {"url": "https://portal/recovered"},
    ]
    with _prices(), patch.object(stripe_gateway, "_client", return_value=client):
        url = stripe_gateway.create_plan_change_session(
            subscription_id="sub_123",
            customer_id="cus_123",
            tier=UserTier.pro,
            return_url="https://app/billing",
        )

    assert url == "https://portal/recovered"
    client.SubscriptionSchedule.release.assert_called_once_with("sub_sched_1")
    assert client.billing_portal.Session.create.call_count == 2


def test_an_expanded_schedule_object_is_accepted_too() -> None:
    """Stripe returns the schedule as an id or an object depending on expansion."""
    client = _stripe_client({**SUBSCRIPTION, "schedule": {"id": "sub_sched_1"}})
    client.billing_portal.Session.create.side_effect = [
        stripe.InvalidRequestError("managed by a schedule", param="subscription"),
        {"url": "https://portal/recovered"},
    ]
    with _prices(), patch.object(stripe_gateway, "_client", return_value=client):
        stripe_gateway.create_plan_change_session(
            subscription_id="sub_123",
            customer_id="cus_123",
            tier=UserTier.pro,
            return_url="https://app/billing",
        )

    client.SubscriptionSchedule.release.assert_called_once_with("sub_sched_1")


def test_a_rejection_with_no_schedule_behind_it_is_not_retried() -> None:
    """Releasing is the repair for one specific state, not a blanket retry."""
    client = _stripe_client()
    client.billing_portal.Session.create.side_effect = stripe.InvalidRequestError(
        "No such price", param="flow_data[subscription_update_confirm][items][0][price]"
    )
    with (
        _prices(),
        patch.object(stripe_gateway, "_client", return_value=client),
        pytest.raises(stripe.InvalidRequestError),
    ):
        stripe_gateway.create_plan_change_session(
            subscription_id="sub_123",
            customer_id="cus_123",
            tier=UserTier.pro,
            return_url="https://app/billing",
        )

    client.SubscriptionSchedule.release.assert_not_called()
    assert client.billing_portal.Session.create.call_count == 1


def test_changing_to_an_unpurchasable_plan_raises_a_clear_503() -> None:
    with (
        patch.object(settings, "STRIPE_SECRET_KEY", "sk_test_x"),
        pytest.raises(HTTPException) as exc,
    ):
        stripe_gateway.create_plan_change_session(
            subscription_id="sub_123",
            customer_id="cus_123",
            tier=UserTier.free,
            return_url="https://app/billing",
        )
    assert exc.value.status_code == 503


def test_a_plan_change_without_credentials_raises_a_clear_503() -> None:
    with (
        patch.multiple(settings, STRIPE_SECRET_KEY=None, STRIPE_PRICE_PRO="price_pro"),
        pytest.raises(HTTPException) as exc,
    ):
        stripe_gateway.create_plan_change_session(
            subscription_id="sub_123",
            customer_id="cus_123",
            tier=UserTier.pro,
            return_url="https://app/billing",
        )
    assert exc.value.status_code == 503
