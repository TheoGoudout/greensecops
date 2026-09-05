"""The only module that calls Stripe.

Every outbound call is funnelled through here so the rest of the codebase never
imports ``stripe`` directly. Two things fall out of that:

* **Self-hosted installs work.** A deployment with no ``STRIPE_SECRET_KEY``
  raises a clear 503 from one place instead of surfacing an SDK error from
  wherever the call happened to be. Nothing else has to know billing is off.
* **Tests do not need Stripe.** The whole suite runs unconfigured; the handful
  of tests that exercise checkout patch this module rather than the SDK.

The webhook parser lives here too, since verifying a signature is as much a
Stripe API concern as making a request.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import stripe
from fastapi import HTTPException

from app.core.config import settings
from app.core.plans import PLANS, get_plan, ordered_plans
from app.models import UserTier

from .errors import stripe_not_configured

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(settings.STRIPE_SECRET_KEY)


def _client() -> Any:
    """Return the Stripe module with the API key applied.

    The SDK is configured through module-level globals rather than a client
    object, so this sets the key and hands the module back; the indirection
    exists so every call site is forced through the configuration check.
    """
    if not settings.STRIPE_SECRET_KEY:
        raise stripe_not_configured()
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def price_id_for(tier: UserTier) -> str | None:
    """The configured Stripe price id for ``tier``, if it is purchasable."""
    plan = get_plan(tier)
    if plan.stripe_price_setting is None:
        return None
    value = getattr(settings, plan.stripe_price_setting, None)
    return str(value) if value else None


def tier_for_price(price_id: str) -> UserTier | None:
    """Reverse ``price_id`` back to a tier.

    Built from the catalog rather than a hand-written mapping, so adding a plan
    cannot leave the webhook unable to recognise what was just bought.
    """
    if not price_id:
        return None
    for tier, plan in PLANS.items():
        if plan.stripe_price_setting is None:
            continue
        if getattr(settings, plan.stripe_price_setting, None) == price_id:
            return tier
    return None


def _is_missing_customer(exc: stripe.StripeError) -> bool:
    """Whether ``exc`` is Stripe rejecting the ``customer`` we sent as gone.

    Narrow on purpose: only a ``resource_missing`` naming the ``customer``
    parameter means the id is stale. Any other invalid-request — a bad price, a
    malformed URL — is a real error that must keep propagating.
    """
    return (
        isinstance(exc, stripe.InvalidRequestError)
        and getattr(exc, "code", None) == "resource_missing"
        and getattr(exc, "param", None) == "customer"
    )


@dataclass(frozen=True)
class CheckoutSession:
    """A started Checkout session, and whether the customer id was rejected.

    ``customer_id_rejected`` is how the caller learns its stored
    ``stripe_customer_id`` no longer exists, so it can clear the column instead
    of failing the same way on the next attempt.
    """

    url: str
    customer_id_rejected: bool = False


def create_checkout_session(
    *,
    tier: UserTier,
    customer_id: str | None,
    customer_email: str | None,
    client_reference_id: str,
    success_url: str,
    cancel_url: str,
) -> CheckoutSession:
    """Start a Checkout session for ``tier`` and return its redirect URL.

    ``client_reference_id`` carries our subscription id through Stripe and back
    on ``checkout.session.completed``, which is how the resulting subscription
    is matched to an account that may not have had a customer id yet.

    A customer deleted in the Stripe dashboard leaves our ``stripe_customer_id``
    pointing at nothing, and Stripe rejects the session outright — which left
    the account unable to buy any plan at all, with no way back from our side.
    So a rejected customer id is retried once as a fresh customer, and reported
    to the caller so the dead id can be cleared.
    """
    price_id = price_id_for(tier)
    if price_id is None:
        raise stripe_not_configured()
    client = _client()
    params: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": client_reference_id,
        # Idempotent from Stripe's side if the user double-clicks: reusing the
        # customer keeps one payment profile per account rather than minting a
        # second one on every checkout attempt.
        "allow_promotion_codes": True,
    }
    if customer_id:
        params["customer"] = customer_id
    elif customer_email:
        params["customer_email"] = customer_email

    try:
        session = client.checkout.Session.create(**params)
    except stripe.StripeError as exc:
        if not (customer_id and _is_missing_customer(exc)):
            raise
        logger.warning(
            "Stripe customer %s no longer exists; starting checkout without it",
            customer_id,
        )
        params.pop("customer")
        if customer_email:
            params["customer_email"] = customer_email
        session = client.checkout.Session.create(**params)
        return CheckoutSession(url=str(session["url"]), customer_id_rejected=True)

    return CheckoutSession(url=str(session["url"]))


def _first_item(subscription: Any) -> Any:
    """The single line item a plan lives on.

    Every subscription we create has exactly one — one price, quantity one —
    so there is no ambiguity about which item a plan change replaces.
    """
    items = subscription["items"]["data"]
    if not items:
        raise stripe_not_configured()
    return items[0]


def _schedule_id(subscription: Any) -> str | None:
    """The id of the subscription schedule driving ``subscription``, if any."""
    schedule = subscription.get("schedule")
    if not schedule:
        return None
    return str(schedule["id"] if isinstance(schedule, dict) else schedule)


# ─── The Customer Portal configuration ───────────────────────────────────────

# Marks the portal configuration this module owns. Stripe cannot filter the
# configuration list server-side, so ours is recognised by reading this key
# back off the candidates rather than by remembering an id somewhere.
_CONFIGURATION_MARKER = {"greensecops": "plan-changes"}

# Resolved configuration ids, keyed by the set of prices each was built for.
# Keying on the prices rather than holding one bare id means a deployment — or
# a test — that changes ``STRIPE_PRICE_*`` resolves afresh instead of reusing a
# configuration that no longer offers the plan being bought.
_CONFIGURATION_CACHE: dict[frozenset[str], str] = {}


def _purchasable_price_ids() -> list[str]:
    """Every configured price a subscription may be switched between."""
    return [
        price_id
        for plan in ordered_plans()
        if (price_id := price_id_for(plan.tier)) is not None
    ]


def _products_for(client: Any, price_ids: list[str]) -> list[dict[str, Any]]:
    """Group ``price_ids`` by the Stripe product each belongs to.

    ``features.subscription_update.products`` is keyed by product, so the price
    ids alone will not do — every one has to be resolved. Grouping rather than
    assuming a product per plan means the catalog works whether the plans are
    separate products or several prices on a single one.
    """
    by_product: dict[str, list[str]] = {}
    for price_id in price_ids:
        product = client.Price.retrieve(price_id)["product"]
        product_id = str(product["id"] if isinstance(product, dict) else product)
        by_product.setdefault(product_id, []).append(price_id)
    return [
        {"product": product_id, "prices": prices}
        for product_id, prices in by_product.items()
    ]


def _configuration_features(products: list[dict[str, Any]]) -> dict[str, Any]:
    """The portal features a plan change needs, and the rules it runs under.

    ``proration_behavior``, ``schedule_at_period_end`` and
    ``trial_update_behavior`` are the whole billing policy for a plan change,
    and they live on the configuration rather than in our code deliberately:
    Stripe applies them *and* explains them on the confirmation page, so what
    the customer is shown and what they are charged come from one place.
    """
    return {
        "subscription_update": {
            "enabled": True,
            # Price is the only thing a plan change moves. Quantity is always
            # one, and promotion codes belong to the initial Checkout.
            "default_allowed_updates": ["price"],
            "products": products,
            # Credits the unused remainder of the plan being left and invoices
            # only the balance, so an upgrade asks for the difference rather
            # than a second full price. Full price resumes at the next renewal.
            "proration_behavior": "always_invoice",
            # A change that lowers the bill waits for the renewal instead of
            # landing now: someone choosing a smaller plan is asking to pay
            # less *next* month, not to forfeit the month already bought.
            "schedule_at_period_end": {
                "conditions": [{"type": "decreasing_item_amount"}]
            },
            # A trialing account keeps its trial rather than being charged the
            # moment it looks at a bigger plan.
            "trial_update_behavior": "continue_trial",
        },
        # The same configuration backs ``create_portal_session``, so it carries
        # the card, history and cancellation features that flow needs too —
        # otherwise opening the portal would show a page with nothing on it.
        "payment_method_update": {"enabled": True},
        "invoice_history": {"enabled": True},
        "subscription_cancel": {"enabled": True},
    }


def _listed_prices(configuration: Any) -> set[str]:
    """The prices ``configuration`` currently allows switching between."""
    update = (configuration.get("features") or {}).get("subscription_update") or {}
    return {
        price
        for product in (update.get("products") or [])
        for price in product["prices"]
    }


def _find_configuration(client: Any) -> Any | None:
    """The portal configuration this module created, if it still exists."""
    listing = client.billing_portal.Configuration.list(active=True, limit=100)
    for configuration in listing["data"]:
        metadata = configuration.get("metadata") or {}
        if all(
            metadata.get(key) == value for key, value in _CONFIGURATION_MARKER.items()
        ):
            return configuration
    return None


def _portal_configuration_id(client: Any) -> str | None:
    """The configuration plan changes are confirmed against, provisioning it.

    Stripe will only move a subscription onto a price the configuration lists,
    so this is derived from the plan catalog rather than pinned by hand: adding
    a plan to ``core/plans.py`` cannot leave the portal unable to sell it. An
    operator who would rather manage the configuration in the dashboard sets
    ``STRIPE_PORTAL_CONFIGURATION_ID`` and none of this runs.

    ``None`` when no price is configured at all: there is no plan to switch to,
    and Stripe refuses a configuration that enables switching to nothing. The
    portal still opens for cards and cancellation on the account default, which
    is the most a deployment in that state could offer anyway.
    """
    if configured := settings.STRIPE_PORTAL_CONFIGURATION_ID:
        return str(configured)
    price_ids = _purchasable_price_ids()
    if not price_ids:
        return None
    cache_key = frozenset(price_ids)
    if cached := _CONFIGURATION_CACHE.get(cache_key):
        return cached

    existing = _find_configuration(client)
    if existing is not None and _listed_prices(existing) == cache_key:
        configuration = existing
    else:
        features = _configuration_features(_products_for(client, price_ids))
        if existing is None:
            configuration = client.billing_portal.Configuration.create(
                features=features, metadata=dict(_CONFIGURATION_MARKER)
            )
        else:
            # The catalog moved. Bring the standing configuration in line
            # rather than minting a second one beside it on every price change.
            configuration = client.billing_portal.Configuration.modify(
                existing["id"], features=features
            )
    configuration_id = str(configuration["id"])
    _CONFIGURATION_CACHE[cache_key] = configuration_id
    return configuration_id


def create_plan_change_session(
    *, subscription_id: str, customer_id: str, tier: UserTier, return_url: str
) -> str:
    """Open the Stripe page that confirms moving a subscription onto ``tier``.

    Sending an already-subscribed customer through Checkout would open a
    *second* Stripe subscription beside the first, so the account would be
    billed for both and our webhook would take whichever event arrived last as
    the truth. A customer who has one changes it — but changing it is money
    moving, so it is confirmed on Stripe's own page rather than on a click
    here. Nothing is charged, and nothing in our database moves, until the
    customer confirms there and the resulting webhook comes back.

    Which way the change goes is the configuration's business, not ours: its
    ``schedule_at_period_end`` condition prorates a more expensive plan onto
    the current period and defers a cheaper one to the renewal. Deciding that
    here as well would be two rules that could drift apart.
    """
    price_id = price_id_for(tier)
    if price_id is None:
        raise stripe_not_configured()
    client = _client()
    subscription = client.Subscription.retrieve(subscription_id)
    params: dict[str, Any] = {
        "customer": customer_id,
        "return_url": return_url,
        "flow_data": {
            "type": "subscription_update_confirm",
            "subscription_update_confirm": {
                "subscription": subscription_id,
                "items": [
                    {
                        "id": _first_item(subscription)["id"],
                        "price": price_id,
                        "quantity": 1,
                    }
                ],
            },
            "after_completion": {
                "type": "redirect",
                "redirect": {"return_url": return_url},
            },
        },
    }
    if configuration_id := _portal_configuration_id(client):
        params["configuration"] = configuration_id
    try:
        session = client.billing_portal.Session.create(**params)
    except stripe.InvalidRequestError:
        schedule_id = _schedule_id(subscription)
        if schedule_id is None:
            raise
        # Left over from when a downgrade was deferred by a schedule of our
        # own: Stripe will not let the portal touch a subscription a schedule
        # is driving. Releasing hands it back to plain recurring billing at the
        # price it is on today, which drops the pending downgrade — the right
        # answer, since the customer is on their way to Stripe to choose again.
        logger.warning(
            "Releasing schedule %s so subscription %s can be changed in the portal",
            schedule_id,
            subscription_id,
        )
        client.SubscriptionSchedule.release(schedule_id)
        session = client.billing_portal.Session.create(**params)
    return str(session["url"])


def create_portal_session(*, customer_id: str, return_url: str) -> str:
    """Open the Stripe Customer Portal for card changes and cancellation.

    Cancellation is deliberately Stripe's job rather than ours: it keeps the
    payment-method UI, the proration rules and the cancel flow in one audited
    place, and the resulting webhooks drive our own state machine.
    """
    client = _client()
    params: dict[str, Any] = {"customer": customer_id, "return_url": return_url}
    # The same configuration a plan change is confirmed against, so "Manage
    # subscription" offers the plans as well rather than opening whatever the
    # account default happens to allow.
    if configuration_id := _portal_configuration_id(client):
        params["configuration"] = configuration_id
    session = client.billing_portal.Session.create(**params)
    return str(session["url"])


def parse_webhook_event(payload: bytes, signature: str | None) -> dict[str, Any]:
    """Verify a webhook signature and return the decoded event.

    Raises the same ``HTTPException``s the route used to raise inline, so an
    unsigned or tampered payload is a 400 rather than a 500.
    """

    if not settings.STRIPE_SECRET_KEY or not settings.STRIPE_WEBHOOK_SECRET:
        raise stripe_not_configured()
    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(
            status_code=400, detail="Invalid Stripe signature"
        ) from None
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return dict(event)
