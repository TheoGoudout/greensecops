"""Structured billing errors.

Every billing refusal leaves through here, and every one of them answers the
same four questions in its ``message``: **what you used, what the cap is, when
it resets, and what to do next**. The previous implementation raised a bare
``"Analyses quota reached for the free tier (50). Upgrade your plan to
continue."`` — true, but it told a user neither how long they were stuck nor
which plan would unstick them.

The ``detail`` payload is a dict rather than a string so the frontend can act
on it (render an Upgrade button pointed at the right plan, show a countdown to
the reset) instead of pattern-matching prose. ``detail.message`` always holds a
complete human-readable sentence, so any client that only knows how to print a
string still shows something useful — see ``extractErrorMessage`` in
``frontend/src/utils.ts``.
"""

from __future__ import annotations

import enum
from datetime import datetime

from fastapi import HTTPException

from app.core.config import settings
from app.core.plans import get_plan, next_tier_above
from app.models.enums import UserTier


class BillingErrorCode(str, enum.Enum):
    """Machine-readable reason a billing check refused a request."""

    # A metered allowance for the current period is exhausted.
    quota_exceeded = "quota_exceeded"
    # The plan does not include this capability at any usage level.
    feature_not_in_plan = "feature_not_in_plan"
    # Payment failed; still inside the grace window, so this is a warning
    # rather than a block. Not raised as an error today, but carried in the
    # subscription payload so the UI can show the banner.
    subscription_past_due = "subscription_past_due"
    # Grace window expired: the account is on Free limits until it pays.
    subscription_unpaid = "subscription_unpaid"
    # Generic payment-required refusal.
    payment_required = "payment_required"
    # The deployment has no Stripe credentials, so checkout/portal cannot run.
    stripe_not_configured = "stripe_not_configured"


# Human-facing meter names. "fixes" alone reads like a count of bugs fixed.
METER_LABELS: dict[str, str] = {
    "analyses": "analyses",
    "fixes": "AI fix generations",
    "repos": "repositories",
}


def billing_url() -> str:
    """Absolute URL of the in-app billing page."""
    return f"{settings.FRONTEND_HOST.rstrip('/')}/billing"


def _format_date(value: datetime | None) -> str | None:
    """``1 September 2026``. Avoids ``%-d``, which is not portable."""
    if value is None:
        return None
    return f"{value.day} {value.strftime('%B %Y')}"


def _reset_clause(resets_at: datetime | None) -> str:
    if resets_at is None:
        return ""
    return f" Your quota resets on {_format_date(resets_at)}."


def _upgrade_clause(tier: UserTier, meter: str) -> str:
    """Name the cheapest plan that actually raises this meter, if any."""
    plan = next_tier_above(tier, meter)
    if plan is None:
        return f" Contact support to raise your {METER_LABELS.get(meter, meter)} limit."
    allowance = plan.limits.get(meter)
    label = METER_LABELS.get(meter, meter)
    if allowance is None:
        return f" Upgrade to {plan.name} ({plan.price_display}) for unlimited {label}."
    suffix = "" if meter == "repos" else "/month"
    return (
        f" Upgrade to {plan.name} ({plan.price_display}) for "
        f"{allowance:,} {label}{suffix}."
    )


def quota_exceeded(
    *,
    meter: str,
    tier: UserTier,
    limit: int,
    used: int,
    requested: int,
    resets_at: datetime | None,
    engine: str | None = None,
) -> HTTPException:
    """402 for an exhausted (or insufficient) metered allowance.

    Distinguishes "you have nothing left" from "you have some left, but this
    one request needs more than that" — a batch re-analysis of twelve workflow
    files against three remaining analyses is a different problem to solve, and
    saying so saves the user a round of guessing.
    """
    plan = get_plan(tier)
    label = METER_LABELS.get(meter, meter)
    remaining = max(limit - used, 0)

    if remaining <= 0:
        if meter == "repos":
            headline = (
                f"You've enabled all {limit:,} repositories included in the "
                f"{plan.name} plan. Disable one to free a slot, or upgrade."
            )
        else:
            headline = (
                f"You've used all {limit:,} {label} included in the "
                f"{plan.name} plan this month."
            )
    else:
        headline = (
            f"This request needs {requested:,} {label} but only {remaining:,} "
            f"of the {plan.name} plan's {limit:,} remain this month."
        )

    # A repo slot is capacity, not consumption: it frees up when a repo is
    # disabled rather than at a period boundary. Dropped from the payload as
    # well as the sentence — a client rendering "resets in 12 days" from the
    # structured field would be just as wrong as the prose would have been.
    resets_at = None if meter == "repos" else resets_at

    return HTTPException(
        status_code=402,
        detail={
            "code": BillingErrorCode.quota_exceeded.value,
            "meter": meter,
            "engine": engine,
            "tier": tier.value,
            "plan": plan.name,
            "limit": limit,
            "used": used,
            "requested": requested,
            "remaining": remaining,
            "resets_at": resets_at.isoformat() if resets_at else None,
            "upgrade_url": billing_url(),
            "message": headline
            + _reset_clause(resets_at)
            + _upgrade_clause(tier, meter),
        },
    )


def feature_not_in_plan(
    *, feature: str, tier: UserTier, required_plan_name: str
) -> HTTPException:
    """402 for a capability the plan does not include at any usage level."""
    plan = get_plan(tier)
    return HTTPException(
        status_code=402,
        detail={
            "code": BillingErrorCode.feature_not_in_plan.value,
            "feature": feature,
            "tier": tier.value,
            "plan": plan.name,
            "upgrade_url": billing_url(),
            "message": (
                f"{feature} is not included in the {plan.name} plan. "
                f"Upgrade to {required_plan_name} or above to enable it."
            ),
        },
    )


def subscription_unpaid(*, grace_expired_at: datetime | None) -> HTTPException:
    """402 once the grace window has closed on a failed payment."""
    when = _format_date(grace_expired_at)
    tail = f" The grace period ended on {when}." if when else ""
    return HTTPException(
        status_code=402,
        detail={
            "code": BillingErrorCode.subscription_unpaid.value,
            "upgrade_url": billing_url(),
            "message": (
                "Your subscription is unpaid, so this account is running on "
                f"Free plan limits.{tail} Update your payment method to "
                "restore your plan — none of your data has been removed."
            ),
        },
    )


def stripe_not_configured() -> HTTPException:
    """503 when the deployment has no Stripe credentials.

    Self-hosted installs run perfectly well without billing; this says so
    plainly instead of surfacing a Stripe SDK stack trace.
    """
    return HTTPException(
        status_code=503,
        detail={
            "code": BillingErrorCode.stripe_not_configured.value,
            "message": (
                "Billing is not configured on this deployment. Set "
                "STRIPE_SECRET_KEY and the plan price ids to enable checkout."
            ),
        },
    )


def payment_required(message: str) -> HTTPException:
    """402 for a billing refusal with no more specific code."""
    return HTTPException(
        status_code=402,
        detail={
            "code": BillingErrorCode.payment_required.value,
            "upgrade_url": billing_url(),
            "message": message,
        },
    )
