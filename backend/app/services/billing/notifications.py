"""Billing emails: what gets sent, when, and with which numbers in it.

Every send goes through ``app.utils.send_email``, which is a no-op unless SMTP
is configured — so development, CI and self-hosted installs without mail stay
silent without any caller needing to know that.

The templates deliberately lead with what has *not* changed. A failed payment
is alarming, and the single most useful thing a dunning email can say is that
the plan is still working and nothing has been deleted. That framing is why
these are written here rather than assembled ad hoc at each call site: the
grace policy is one decision, and its wording should be too.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlmodel import Session

from app.core.config import settings
from app.core.plans import get_plan, next_tier_above
from app.models import BillingSubscription, Invoice, User
from app.utils import render_email_template, send_email

from .errors import METER_LABELS, billing_url
from .lifecycle import effective_tier, grace_remaining_days

logger = logging.getLogger(__name__)

# Email kind -> (built template filename, subject). Subjects are Jinja too, so
# they can carry the plan name or a percentage.
_TEMPLATES: dict[str, tuple[str, str]] = {
    "subscription_started": (
        "billing_subscription_started.html",
        "{project_name} - Welcome to {plan_name}",
    ),
    "plan_changed": (
        "billing_plan_changed.html",
        "{project_name} - Your plan is now {plan_name}",
    ),
    "payment_failed": (
        "billing_payment_failed.html",
        "{project_name} - Payment failed, {days_remaining} day(s) to update",
    ),
    "grace_expired": (
        "billing_grace_expired.html",
        "{project_name} - Your account is now on Free plan limits",
    ),
    "subscription_canceled": (
        "billing_subscription_canceled.html",
        "{project_name} - Your subscription has been cancelled",
    ),
    "invoice_paid": (
        "billing_invoice_paid.html",
        "{project_name} - Payment received",
    ),
    "quota_warning": (
        "billing_quota_warning.html",
        "{project_name} - {percent}% of your {meter_label} used",
    ),
    "trial_ending": (
        "billing_trial_ending.html",
        "{project_name} - Your trial ends soon",
    ),
}

_UNLIMITED = "Unlimited"


def _limit_display(value: int | None) -> str:
    return _UNLIMITED if value is None else f"{value:,}"


def _date_display(value: datetime | None) -> str:
    if value is None:
        return "—"
    return f"{value.day} {value.strftime('%B %Y')}"


def _money(cents: int | None, currency: str = "usd") -> str:
    """Format a minor-unit amount. Amounts are never floats in storage."""
    if cents is None:
        return "—"
    symbol = {"usd": "$", "eur": "€", "gbp": "£"}.get(currency.lower(), "")
    return f"{symbol}{cents / 100:,.2f}" + ("" if symbol else f" {currency.upper()}")


def _base_context(user: User, sub: BillingSubscription) -> dict[str, Any]:
    """The fields every billing template can rely on being present."""
    plan = get_plan(sub.tier)
    limits = plan.limits
    return {
        "project_name": settings.PROJECT_NAME,
        "username": user.full_name or user.email,
        "email": user.email,
        "billing_url": billing_url(),
        "plan_name": plan.name,
        "price_display": plan.price_display,
        "analyses_limit": _limit_display(limits.analyses),
        "fixes_limit": _limit_display(limits.fixes),
        "repos_limit": _limit_display(limits.repos),
        "period_start": _date_display(sub.period_start),
        "period_end": _date_display(sub.period_end),
        "grace_expires_at": _date_display(sub.grace_expires_at),
        "days_remaining": grace_remaining_days(sub),
        "trial_end": _date_display(sub.trial_end),
        # Present but empty unless the caller passes an invoice, so a template
        # referencing them never renders the literal string "Undefined".
        "invoice_url": billing_url(),
        "amount_due": "—",
        "amount_paid": "—",
    }


def _invoice_context(invoice: Invoice | None) -> dict[str, Any]:
    if invoice is None:
        return {}
    return {
        "invoice_url": invoice.hosted_invoice_url or billing_url(),
        "amount_due": _money(invoice.amount_due_cents, invoice.currency),
        "amount_paid": _money(invoice.amount_paid_cents, invoice.currency),
        "period_start": _date_display(invoice.period_start),
        "period_end": _date_display(invoice.period_end),
    }


def send_billing_email(
    session: Session,
    sub: BillingSubscription,
    kind: str,
    *,
    invoice: Invoice | None = None,
    **extra: Any,
) -> bool:
    """Render and send one billing email. Returns whether it was sent.

    Returns ``False`` rather than raising when mail is not configured or the
    subscription's user has gone — a webhook must not fail because SMTP is
    down, since Stripe would retry the whole handler and duplicate whatever
    else it had already done.
    """
    if not settings.emails_enabled:
        logger.debug("Email disabled — skipping %s notification", kind)
        return False
    template = _TEMPLATES.get(kind)
    if template is None:
        logger.warning("Unknown billing email kind %r", kind)
        return False
    user = session.get(User, sub.user_id)
    if user is None:
        return False

    template_name, subject_template = template
    context = _base_context(user, sub)
    context.update(_invoice_context(invoice))
    context.update(extra)

    html_content = render_email_template(template_name=template_name, context=context)
    # ``str.format`` rather than Jinja: subjects are single-line and every
    # placeholder is already in ``context``, so a template engine would only
    # add a way for a missing key to raise mid-send.
    subject = subject_template.format(
        **{**context, **{"percent": context.get("percent", "")}}
    )
    send_email(email_to=user.email, subject=subject, html_content=html_content)
    logger.info("Sent %s billing email to %s", kind, user.email)
    return True


def send_quota_warning(
    session: Session,
    sub: BillingSubscription,
    meter: str,
    used: int,
    limit: int,
    percent: int,
) -> bool:
    """Warn before the wall, not after it.

    Sent at 80% and again at 100%. The upgrade hint names the cheapest plan
    that actually raises *this* meter, so the mail is a decision rather than a
    nudge to go and read the pricing page.
    """
    tier = effective_tier(sub)
    upgrade = next_tier_above(tier, meter)
    label = METER_LABELS.get(meter, meter)
    if upgrade is None:
        hint = "Contact support if you need a higher limit."
    else:
        allowance = upgrade.limits.get(meter)
        allowance_text = "unlimited" if allowance is None else f"{allowance:,}"
        hint = (
            f"Upgrading to {upgrade.name} ({upgrade.price_display}) raises this "
            f"to {allowance_text} {label} a month."
        )
    return send_billing_email(
        session,
        sub,
        "quota_warning",
        meter_label=label,
        used=f"{used:,}",
        limit=f"{limit:,}",
        percent=percent,
        resets_at=_date_display(sub.period_end),
        upgrade_hint=hint,
    )
