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
from datetime import datetime, timezone
from typing import Any

import stripe
from fastapi import HTTPException

from app.core.config import settings
from app.core.plans import PLANS, get_plan
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


@dataclass(frozen=True)
class PlanChange:
    """What happened when an existing subscription was moved to another plan.

    ``effective_at`` is ``None`` when the new plan is live now, and the moment
    it starts when the change was deferred to the renewal. The caller needs the
    difference to tell the user what they just bought.
    """

    tier: UserTier
    effective_at: datetime | None = None

    @property
    def is_immediate(self) -> bool:
        return self.effective_at is None


def _first_item(subscription: Any) -> Any:
    """The single line item a plan lives on.

    Every subscription we create has exactly one — one price, quantity one —
    so there is no ambiguity about which item a plan change replaces.
    """
    items = subscription["items"]["data"]
    if not items:
        raise stripe_not_configured()
    return items[0]


def _phase_price(item: Any) -> str:
    """A schedule phase's price id, whether Stripe expanded it or not."""
    price = item.get("price")
    return str(price["id"] if isinstance(price, dict) else price)


def _upgrade(client: Any, subscription: Any, price_id: str) -> PlanChange:
    """Swap the price now and invoice the difference.

    ``always_invoice`` is the point of the exercise: it credits the unused
    remainder of the plan being left and bills only the balance, so the first
    payment on the new plan is the difference rather than a second full price.
    Full price resumes at the next renewal on its own.
    """
    client.Subscription.modify(
        subscription["id"],
        items=[{"id": _first_item(subscription)["id"], "price": price_id}],
        proration_behavior="always_invoice",
    )
    return PlanChange(tier=tier_for_price(price_id) or UserTier.free)


def _open_schedule(client: Any, subscription: Any) -> Any:
    """The subscription's schedule, creating one if it has none.

    A second downgrade before the first has taken effect must edit the
    schedule already standing rather than try to create another — Stripe
    refuses that, and the user would be stuck on a downgrade they changed
    their mind about.
    """
    if existing := subscription.get("schedule"):
        schedule_id = existing["id"] if isinstance(existing, dict) else existing
        return client.SubscriptionSchedule.retrieve(schedule_id)
    return client.SubscriptionSchedule.create(from_subscription=subscription["id"])


def _downgrade(client: Any, subscription: Any, price_id: str) -> PlanChange:
    """Leave the paid-for plan running, and start the cheaper one at renewal.

    A downgrade taking effect immediately would either refund time already
    bought or silently forfeit it. Neither is what someone choosing a smaller
    plan is asking for: they are asking to pay less *next* month.
    """
    schedule = _open_schedule(client, subscription)
    current = schedule["phases"][0]
    client.SubscriptionSchedule.modify(
        schedule["id"],
        phases=[
            {
                "items": [
                    {"price": _phase_price(item), "quantity": 1}
                    for item in current["items"]
                ],
                "start_date": current["start_date"],
                "end_date": current["end_date"],
            },
            {
                "items": [{"price": price_id, "quantity": 1}],
                "iterations": 1,
                # The switch lands on the period boundary, so there is nothing
                # to prorate — asking for prorations here would invent a
                # zero-value adjustment on the invoice.
                "proration_behavior": "none",
            },
        ],
        # Once the cheaper phase has run, hand the subscription back to normal
        # recurring billing at that price instead of cancelling it.
        end_behavior="release",
    )
    return PlanChange(
        tier=tier_for_price(price_id) or UserTier.free,
        effective_at=datetime.fromtimestamp(current["end_date"], tz=timezone.utc),
    )


def change_subscription_plan(
    *, subscription_id: str, tier: UserTier, immediate: bool
) -> PlanChange:
    """Move a live subscription onto ``tier``'s price.

    Sending an already-subscribed customer through Checkout would open a
    *second* Stripe subscription beside the first, so the account would be
    billed for both and our webhook would take whichever event arrived last as
    the truth. A customer who has one changes it.

    ``immediate`` says which way the change goes, which the caller decides from
    the two plans' prices: an upgrade starts now with the unused remainder
    credited, a downgrade starts at the renewal.
    """
    price_id = price_id_for(tier)
    if price_id is None:
        raise stripe_not_configured()
    client = _client()
    subscription = client.Subscription.retrieve(subscription_id)
    if immediate:
        return _upgrade(client, subscription, price_id)
    return _downgrade(client, subscription, price_id)


def create_portal_session(*, customer_id: str, return_url: str) -> str:
    """Open the Stripe Customer Portal for card changes and cancellation.

    Cancellation is deliberately Stripe's job rather than ours: it keeps the
    payment-method UI, the proration rules and the cancel flow in one audited
    place, and the resulting webhooks drive our own state machine.
    """
    client = _client()
    session = client.billing_portal.Session.create(
        customer=customer_id, return_url=return_url
    )
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
        event = stripe.Webhook.construct_event(  # type: ignore[no-untyped-call]
            payload, signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(
            status_code=400, detail="Invalid Stripe signature"
        ) from None
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return dict(event)
