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


def create_checkout_session(
    *,
    tier: UserTier,
    customer_id: str | None,
    customer_email: str | None,
    client_reference_id: str,
    success_url: str,
    cancel_url: str,
) -> str:
    """Start a Checkout session for ``tier`` and return its redirect URL.

    ``client_reference_id`` carries our subscription id through Stripe and back
    on ``checkout.session.completed``, which is how the resulting subscription
    is matched to an account that may not have had a customer id yet.
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
    session = client.checkout.Session.create(**params)
    return str(session["url"])


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
