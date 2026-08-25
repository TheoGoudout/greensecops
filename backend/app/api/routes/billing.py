"""Billing endpoints: plan, usage, invoices, checkout, portal, OSS applications.

This module is deliberately thin. Quota enforcement lives in
``services/billing/quota.py`` (the workers need it too, and a Celery task
importing an API route module to reach it would be backwards); the plan catalog
lives in ``core/plans.py``; every Stripe call goes through
``services/billing/stripe_gateway.py``. What is left here is HTTP: read the
request, call a service, shape a response.

The one piece of real logic that stays is the webhook handler, because
translating Stripe's event vocabulary into our lifecycle events is an
integration concern rather than a domain one.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import Header, HTTPException, Request
from sqlmodel import Session, col, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_or_404,
)
from app.api.router import Role, RoleRouter
from app.core.config import settings
from app.core.plans import get_plan, ordered_plans
from app.core.rate_limit import LIMIT_EXPENSIVE, LIMIT_PUBLIC, LIMIT_WEBHOOK
from app.models import (
    BillingSubscription,
    BillingSubscriptionPublic,
    BillingWebhookEvent,
    CheckoutRequest,
    CheckoutSessionPublic,
    Invoice,
    InvoicePublic,
    InvoiceStatus,
    OssApplication,
    OssApplicationCreate,
    OssApplicationPublic,
    OssApplicationReview,
    OssApplicationStatus,
    PlanLimitsPublic,
    PlanPublic,
    SubscriptionStatus,
    UsageBreakdownPublic,
    UsagePublic,
    User,
    UserTier,
    get_datetime_utc,
)
from app.services.billing import errors, stripe_gateway
from app.services.billing import usage as usage_service
from app.services.billing.lifecycle import (
    apply_tier,
    effective_tier,
    get_or_create_subscription,
    set_stripe_period,
    transition,
)
from app.services.billing.lifecycle import (
    # Aliased: the route below owns the ``get_subscription`` name, because it
    # is the OpenAPI operation id and therefore the generated client's method.
    get_subscription as load_subscription,
)
from app.services.billing.notifications import send_billing_email
from app.services.billing.quota import snapshot

logger = logging.getLogger(__name__)

router = RoleRouter(prefix="/billing", tags=["billing"])


# ─── Plan & usage ────────────────────────────────────────────────────────────


def _limits_public(tier: UserTier) -> PlanLimitsPublic:
    limits = get_plan(tier).limits
    return PlanLimitsPublic(
        analyses=limits.analyses, fixes=limits.fixes, repos=limits.repos
    )


# The one unauthenticated route in this module, and deliberately so: the plan
# catalog is public pricing copy with nothing account-specific in it, and it has
# never required a token. Declared guest rather than user so that stays a
# decision on the record instead of an accident.
@router.get(
    "/plans", role=Role.guest, limit=LIMIT_PUBLIC, response_model=list[PlanPublic]
)
def list_plans() -> list[PlanPublic]:
    """The plan catalog, in presentation order.

    Served rather than duplicated in the frontend so the app's plan cards, the
    marketing pricing table and the quota enforcer cannot disagree about what a
    plan includes — they all read ``core/plans.PLANS``.
    """
    return [
        PlanPublic(
            tier=plan.tier,
            name=plan.name,
            price_cents=plan.price_cents,
            price_display=plan.price_display,
            tagline=plan.tagline,
            limits=PlanLimitsPublic(
                analyses=plan.limits.analyses,
                fixes=plan.limits.fixes,
                repos=plan.limits.repos,
            ),
            auto_fix=plan.auto_fix,
            public_repos_only=plan.public_repos_only,
            # A plan Stripe cannot sell is not offered as a button. On a
            # deployment with no Stripe credentials that is every plan.
            is_purchasable=plan.is_purchasable and settings.billing_enabled,
            features=list(plan.features),
        )
        for plan in ordered_plans()
    ]


@router.get("/subscription", role=Role.user, response_model=BillingSubscriptionPublic)
def get_subscription(
    session: SessionDep,
    current_user: CurrentUser,
) -> BillingSubscriptionPublic:
    snap = snapshot(session, current_user)
    sub = snap.subscription

    return BillingSubscriptionPublic(
        id=sub.id,
        tier=sub.tier,
        # Both, deliberately: showing only one would either hide that a Pro
        # account is currently limited to Free, or hide that it is still a Pro
        # account waiting to be restored.
        effective_tier=effective_tier(sub),
        status=sub.status,
        analyses_used=snap.analyses_used,
        fixes_used=snap.fixes_used,
        repos_used=snap.repos_used,
        period_start=sub.period_start,
        period_end=sub.period_end,
        grace_expires_at=sub.grace_expires_at,
        cancel_at_period_end=sub.cancel_at_period_end,
        trial_end=sub.trial_end,
        billing_enabled=settings.billing_enabled,
    )


@router.get("/usage", role=Role.user, response_model=UsagePublic)
def get_usage(
    session: SessionDep,
    current_user: CurrentUser,
) -> UsagePublic:
    """Current-period usage with the per-engine split behind each meter.

    The breakdown is the point: "you are at 90% of your analyses" is not
    actionable until you know it was the Terraform roots rather than the
    workflows.
    """
    snap = snapshot(session, current_user)
    sub = snap.subscription
    breakdown = usage_service.period_breakdown(
        session, current_user.id, sub.period_start, sub.period_end
    )
    return UsagePublic(
        period_start=sub.period_start,
        period_end=sub.period_end,
        analyses_used=snap.analyses_used,
        fixes_used=snap.fixes_used,
        repos_used=snap.repos_used,
        limits=_limits_public(effective_tier(sub)),
        breakdown=[
            UsageBreakdownPublic(meter=meter, engine=engine, quantity=quantity)
            for meter, engine, quantity in breakdown
        ],
    )


@router.get("/limits", role=Role.user)
def get_tier_limits(
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, object]:
    """The limits actually being applied to this account.

    Reads the subscription rather than ``User.tier``. Those two used to be read
    by different endpoints, so an account could be metered against one and
    shown the other.
    """
    sub = get_or_create_subscription(session, current_user)
    tier = effective_tier(sub)
    limits = get_plan(tier).limits
    return {
        "tier": tier,
        "limits": {
            "analyses": limits.analyses,
            "fixes": limits.fixes,
            "repos": limits.repos,
        },
    }


@router.get("/invoices", role=Role.user, response_model=list[InvoicePublic])
def list_invoices(
    session: SessionDep,
    current_user: CurrentUser,
) -> list[InvoicePublic]:
    sub = load_subscription(session, current_user.id)
    if sub is None:
        return []
    invoices = session.exec(
        select(Invoice)
        .where(Invoice.subscription_id == sub.id)
        .order_by(col(Invoice.created_at).desc())
        .limit(100)
    ).all()
    return [InvoicePublic.model_validate(inv, from_attributes=True) for inv in invoices]


# ─── Checkout & portal ───────────────────────────────────────────────────────


@router.post(
    "/checkout",
    role=Role.user,
    limit=LIMIT_EXPENSIVE,
    response_model=CheckoutSessionPublic,
)
def create_checkout(
    body: CheckoutRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> CheckoutSessionPublic:
    """Start a Stripe Checkout session for ``body.tier``."""
    plan = get_plan(body.tier)
    if not plan.is_purchasable:
        # Free is the default state, and open_source is granted by review — a
        # "buy" button for either would be a dead end, so say which it is.
        raise errors.payment_required(
            f"The {plan.name} plan cannot be purchased directly."
            + (
                " Apply for it from the billing page."
                if body.tier == UserTier.open_source
                else " Cancel your subscription from the billing portal to return to Free."
            )
        )
    sub = get_or_create_subscription(session, current_user)
    if sub.tier == body.tier and sub.status in (
        SubscriptionStatus.active,
        SubscriptionStatus.trialing,
    ):
        raise errors.payment_required(f"You are already on the {plan.name} plan.")

    url = stripe_gateway.create_checkout_session(
        tier=body.tier,
        customer_id=sub.stripe_customer_id,
        customer_email=current_user.email,
        # Carries our subscription id through Stripe and back, which is how the
        # resulting subscription is matched to an account that may not have had
        # a customer id yet.
        client_reference_id=str(sub.id),
        success_url=f"{errors.billing_url()}?checkout=success",
        cancel_url=f"{errors.billing_url()}?checkout=cancelled",
    )
    return CheckoutSessionPublic(url=url)


@router.post(
    "/portal",
    role=Role.user,
    limit=LIMIT_EXPENSIVE,
    response_model=CheckoutSessionPublic,
)
def create_portal(
    session: SessionDep,
    current_user: CurrentUser,
) -> CheckoutSessionPublic:
    """Open the Stripe Customer Portal for card changes and cancellation."""
    sub = load_subscription(session, current_user.id)
    if sub is None or not sub.stripe_customer_id:
        raise errors.payment_required(
            "There is no payment method on this account yet. Choose a plan to "
            "get started."
        )
    url = stripe_gateway.create_portal_session(
        customer_id=sub.stripe_customer_id, return_url=errors.billing_url()
    )
    return CheckoutSessionPublic(url=url)


# ─── Open-source applications ────────────────────────────────────────────────


@router.post(
    "/oss-application",
    role=Role.user,
    response_model=OssApplicationPublic,
    status_code=201,
)
def create_oss_application(
    body: OssApplicationCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> OssApplicationPublic:
    """Apply for the granted open-source plan.

    The pricing page has advertised this since launch with nothing behind the
    button. Approval stays a human decision — whether a project is genuinely
    open source is not something to infer from a URL.
    """
    existing = session.exec(
        select(OssApplication)
        .where(OssApplication.user_id == current_user.id)
        .where(OssApplication.status == OssApplicationStatus.pending)
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="You already have an open-source application under review.",
        )
    application = OssApplication(
        user_id=current_user.id,
        repo_url=body.repo_url,
        license_name=body.license_name,
        justification=body.justification,
    )
    session.add(application)
    session.commit()
    session.refresh(application)
    return OssApplicationPublic.model_validate(application, from_attributes=True)


@router.get(
    "/oss-application", role=Role.user, response_model=list[OssApplicationPublic]
)
def list_my_oss_applications(
    session: SessionDep,
    current_user: CurrentUser,
) -> list[OssApplicationPublic]:
    applications = session.exec(
        select(OssApplication)
        .where(OssApplication.user_id == current_user.id)
        .order_by(col(OssApplication.created_at).desc())
    ).all()
    return [
        OssApplicationPublic.model_validate(a, from_attributes=True)
        for a in applications
    ]


@router.get(
    "/oss-applications",
    role=Role.admin,
    response_model=list[OssApplicationPublic],
)
def list_oss_applications(
    session: SessionDep,
    status: OssApplicationStatus | None = None,
) -> list[OssApplicationPublic]:
    """The review queue, newest first."""
    query = select(OssApplication)
    if status is not None:
        query = query.where(OssApplication.status == status)
    applications = session.exec(
        query.order_by(col(OssApplication.created_at).desc()).limit(200)
    ).all()
    return [
        OssApplicationPublic.model_validate(a, from_attributes=True)
        for a in applications
    ]


@router.patch(
    "/oss-applications/{application_id}",
    role=Role.admin,
    response_model=OssApplicationPublic,
)
def review_oss_application(
    application_id: uuid.UUID,
    body: OssApplicationReview,
    session: SessionDep,
    current_user: CurrentUser,
) -> OssApplicationPublic:
    """Approve or reject an application; approval grants the plan immediately."""
    application = get_or_404(session, OssApplication, application_id)
    if application.status != OssApplicationStatus.pending:
        raise HTTPException(
            status_code=409,
            detail=f"Application was already {application.status.value}.",
        )
    application.status = (
        OssApplicationStatus.approved if body.approve else OssApplicationStatus.rejected
    )
    application.review_note = body.review_note
    application.reviewed_by_id = current_user.id
    application.reviewed_at = get_datetime_utc()
    session.add(application)

    if body.approve:
        applicant = session.get(User, application.user_id)
        if applicant is not None:
            sub = get_or_create_subscription(session, applicant)
            apply_tier(session, sub, UserTier.open_source)
    session.commit()
    session.refresh(application)
    return OssApplicationPublic.model_validate(application, from_attributes=True)


# ─── Stripe webhook ──────────────────────────────────────────────────────────


def _sub_by_stripe_ids(
    session: Session, customer_id: str | None, stripe_sub_id: str | None
) -> BillingSubscription | None:
    """Find a subscription by customer id, falling back to subscription id.

    Both are tried because the two arrive at different times: a Checkout
    session knows the customer before we have stored a subscription id, and a
    subscription update knows the subscription id before a customer has been
    attached to our row.
    """
    if customer_id:
        sub = session.exec(
            select(BillingSubscription).where(
                BillingSubscription.stripe_customer_id == customer_id
            )
        ).first()
        if sub is not None:
            return sub
    if stripe_sub_id:
        return session.exec(
            select(BillingSubscription).where(
                BillingSubscription.stripe_subscription_id == stripe_sub_id
            )
        ).first()
    return None


def _period_from_items(data: dict[str, Any]) -> tuple[int | None, int | None]:
    """Extract the current period, tolerating both Stripe API shapes.

    Newer versions moved these onto the subscription item; older ones keep them
    on the subscription itself.
    """
    items = data.get("items", {}).get("data", [])
    item = items[0] if items else {}
    return (
        item.get("current_period_start") or data.get("current_period_start"),
        item.get("current_period_end") or data.get("current_period_end"),
    )


# Stripe subscription status -> the lifecycle events that could produce it,
# in the order they should be attempted.
_STATUS_EVENTS: dict[str, tuple[str, ...]] = {
    "trialing": ("trial_started",),
    "active": (
        "checkout_completed",
        "trial_converted",
        "payment_succeeded",
        "resumed",
    ),
    "past_due": ("payment_failed", "trial_ended"),
    "incomplete": ("payment_failed", "trial_ended"),
    # Stripe's terminal dunning state maps onto ours via the grace boundary:
    # if we had not noticed the failure yet, record it and then expire it.
    "unpaid": ("grace_expired", "payment_failed"),
    "canceled": ("subscription_deleted",),
}


def _first_legal(
    session: Session, sub: BillingSubscription, events: tuple[str, ...]
) -> bool:
    """Fire the first of ``events`` that is legal from the current state."""
    for event in events:
        if transition(session, sub, event):
            return True
    return False


def _handle_subscription_upsert(session: Session, data: dict[str, Any]) -> None:
    """Apply ``customer.subscription.created|updated``.

    Stripe's ``status`` is the authority on payment state, so it is mapped onto
    our lifecycle events rather than assigned to the column directly — that way
    an impossible jump is rejected by the machine instead of being written.
    """
    customer_id = data.get("customer")
    stripe_sub_id = data.get("id")
    sub = _sub_by_stripe_ids(session, customer_id, stripe_sub_id)
    if sub is None:
        logger.warning("No subscription found for Stripe customer %s", customer_id)
        return

    items = data.get("items", {}).get("data", [])
    price_id = items[0]["price"]["id"] if items else ""
    tier = stripe_gateway.tier_for_price(price_id)
    stripe_status = data.get("status", "")

    sub.stripe_subscription_id = stripe_sub_id or sub.stripe_subscription_id
    sub.stripe_customer_id = customer_id or sub.stripe_customer_id
    set_stripe_period(sub, *_period_from_items(data))
    if trial_end := data.get("trial_end"):
        sub.trial_end = datetime.fromtimestamp(trial_end, tz=timezone.utc)
    session.add(sub)

    if tier is not None and stripe_status in ("active", "trialing", "past_due"):
        # Keep the purchased tier current even while past_due: the user still
        # bought Pro, they are simply behind on paying for it.
        if tier != sub.tier:
            apply_tier(session, sub, tier)
            transition(session, sub, "plan_changed")
        else:
            apply_tier(session, sub, tier)
    session.commit()

    # Stripe's status -> our lifecycle event. ``transition`` is a no-op when the
    # event is illegal from the current state, which is what makes redelivered
    # and out-of-order webhooks safe.
    # Several of our events can lead to the same Stripe status depending on
    # where the subscription currently is, so each status names the events that
    # could reach it and the first legal one wins. ``transition`` returning
    # False simply means the subscription was already there.
    _first_legal(session, sub, _STATUS_EVENTS.get(stripe_status, ()))

    if data.get("cancel_at_period_end"):
        transition(session, sub, "cancel_requested")


def _handle_invoice(session: Session, data: dict[str, Any], event_type: str) -> None:
    """Mirror an invoice and drive the payment lifecycle from it.

    Invoices are stored so billing history survives independently of Stripe,
    and so a dunning email can link straight to the thing that needs paying.
    """
    customer_id = data.get("customer")
    stripe_sub_id = data.get("subscription")
    sub = _sub_by_stripe_ids(session, customer_id, stripe_sub_id)
    if sub is None:
        logger.warning("Invoice %s has no matching subscription", data.get("id"))
        return

    stripe_invoice_id = str(data.get("id") or "")
    if not stripe_invoice_id:
        return
    invoice = session.exec(
        select(Invoice).where(Invoice.stripe_invoice_id == stripe_invoice_id)
    ).first()
    if invoice is None:
        invoice = Invoice(subscription_id=sub.id, stripe_invoice_id=stripe_invoice_id)

    status_map = {
        "draft": InvoiceStatus.draft,
        "open": InvoiceStatus.open,
        "paid": InvoiceStatus.paid,
        "void": InvoiceStatus.void,
        "uncollectible": InvoiceStatus.uncollectible,
    }
    invoice.status = status_map.get(str(data.get("status")), invoice.status)
    invoice.amount_due_cents = int(data.get("amount_due") or 0)
    invoice.amount_paid_cents = int(data.get("amount_paid") or 0)
    invoice.currency = str(data.get("currency") or "usd")
    invoice.number = data.get("number")
    invoice.hosted_invoice_url = data.get("hosted_invoice_url")
    invoice.invoice_pdf = data.get("invoice_pdf")
    if period_start := data.get("period_start"):
        invoice.period_start = datetime.fromtimestamp(period_start, tz=timezone.utc)
    if period_end := data.get("period_end"):
        invoice.period_end = datetime.fromtimestamp(period_end, tz=timezone.utc)
    if due_date := data.get("due_date"):
        invoice.due_at = datetime.fromtimestamp(due_date, tz=timezone.utc)
    session.add(invoice)
    session.commit()

    if event_type == "invoice.paid":
        invoice.paid_at = get_datetime_utc()
        session.add(invoice)
        session.commit()
        # Recovery from either side of the grace boundary, restoring the plan
        # in full rather than leaving the account on Free until the next cycle.
        _first_legal(
            session,
            sub,
            ("payment_succeeded", "checkout_completed", "trial_converted"),
        )
        _notify(session, sub, "invoice_paid", invoice=invoice)
    elif event_type == "invoice.payment_failed":
        if transition(session, sub, "payment_failed"):
            # Reminder zero goes out on the transition rather than waiting for
            # the next daily dunning run, so the first the user hears of it is
            # not up to 24 hours late.
            _notify(session, sub, "payment_failed", invoice=invoice)


def _notify(
    session: Session, sub: BillingSubscription, kind: str, **context: Any
) -> None:
    """Send a billing email, never letting a delivery failure break a webhook.

    Stripe retries any non-2xx, so raising out of a handler because SMTP was
    briefly down would re-run the whole handler — and re-send whatever did
    succeed.
    """

    try:
        send_billing_email(session, sub, kind, **context)
    except Exception:
        logger.exception("Failed to send %s billing email for %s", kind, sub.id)


@router.post("/webhook/stripe", role=Role.service, limit=LIMIT_WEBHOOK, status_code=200)
async def stripe_webhook(
    request: Request,
    session: SessionDep,
    stripe_signature: str | None = Header(default=None, alias="stripe-signature"),
) -> dict[str, str]:
    """Translate Stripe's events into lifecycle transitions.

    Idempotent by event id: Stripe retries on any non-2xx and redelivers on its
    own schedule, and without this a replayed ``invoice.payment_failed`` would
    re-send a dunning email while a replayed subscription update would re-run a
    transition.
    """
    payload = await request.body()
    event = stripe_gateway.parse_webhook_event(payload, stripe_signature)

    event_id = str(event.get("id") or "")
    event_type: str = str(event["type"])
    if event_id:
        already = session.exec(
            select(BillingWebhookEvent).where(
                BillingWebhookEvent.stripe_event_id == event_id
            )
        ).first()
        if already is not None:
            logger.info(
                "Ignoring redelivered Stripe event %s (%s)", event_id, event_type
            )
            return {"status": "duplicate"}

    data = dict(event["data"]["object"])

    if event_type in ("customer.subscription.created", "customer.subscription.updated"):
        _handle_subscription_upsert(session, data)

    elif event_type == "customer.subscription.deleted":
        sub = _sub_by_stripe_ids(session, data.get("customer"), data.get("id"))
        if sub is not None:
            transition(session, sub, "subscription_deleted")
            # The tier reverts to free only once the subscription is really
            # gone; ``effective_tier`` already reports Free from the moment it
            # entered a non-entitled state.
            apply_tier(session, sub, UserTier.free)
            session.commit()
            _notify(session, sub, "subscription_canceled")

    elif event_type == "checkout.session.completed":
        customer_id = data.get("customer", "")
        stripe_sub_id = data.get("subscription", "")
        reference = data.get("client_reference_id")
        sub = None
        if reference:
            try:
                sub = session.get(BillingSubscription, uuid.UUID(str(reference)))
            except ValueError:
                sub = None
        if sub is None:
            sub = _sub_by_stripe_ids(session, customer_id, stripe_sub_id)
        if sub is not None:
            sub.stripe_customer_id = customer_id or sub.stripe_customer_id
            sub.stripe_subscription_id = stripe_sub_id or sub.stripe_subscription_id
            session.add(sub)
            session.commit()
            if transition(session, sub, "checkout_completed"):
                _notify(session, sub, "subscription_started")

    elif event_type in (
        "invoice.paid",
        "invoice.payment_failed",
        "invoice.finalized",
        "invoice.voided",
        "invoice.marked_uncollectible",
    ):
        _handle_invoice(session, data, event_type)

    elif event_type == "customer.subscription.trial_will_end":
        sub = _sub_by_stripe_ids(session, data.get("customer"), data.get("id"))
        if sub is not None:
            _notify(session, sub, "trial_ending")

    else:
        logger.debug("Unhandled Stripe event type: %s", event_type)

    if event_id:
        session.add(
            BillingWebhookEvent(stripe_event_id=event_id, event_type=event_type)
        )
        session.commit()
    return {"status": "ok"}
