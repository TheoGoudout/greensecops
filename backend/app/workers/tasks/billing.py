"""Billing background work: dunning, grace expiry, and quota warnings.

Runs daily. Three passes, in this order:

1. **Dunning.** For every ``past_due`` subscription, send the reminder due
   today and record which one it was.
2. **Grace expiry.** Subscriptions whose window has closed move to ``unpaid``,
   which is the first moment the account is actually limited.
3. **Cancellations.** Subscriptions cancelled at period end whose period has
   now ended become ``canceled``.

Reminders are staged by *index*, not by date arithmetic at send time. That is
what makes the task safe to re-run: the persisted ``dunning_stage`` is the
record of what has gone out, so a beat that fires twice, a worker that restarts
mid-pass, or a redelivered Stripe webhook cannot send the same reminder again.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import engine
from app.core.plans import DEFAULT_TIER, limits_for
from app.models import (
    BillingSubscription,
    SubscriptionStatus,
    UsageMeter,
    User,
    get_datetime_utc,
)
from app.services.billing.lifecycle import (
    apply_tier,
    effective_tier,
    ensure_current_period,
    transition,
)
from app.services.billing.notifications import send_billing_email, send_quota_warning
from app.services.billing.usage import enabled_repo_ids, period_usage
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Warn once when a meter crosses each of these, so a user hears about a wall
# before they hit it rather than from a 402.
_WARN_THRESHOLDS = (80, 100)


def _due_stage(days_elapsed: int) -> int:
    """How many reminders *should* have gone out after ``days_elapsed`` days.

    ``BILLING_DUNNING_DAYS`` is the schedule (day 0, 3, 7, 13 by default); the
    stage is simply how many of those days have passed. Comparing that to the
    persisted stage tells the task whether it owes the user an email, without
    needing to know when the last one was actually sent.
    """
    return sum(1 for day in settings.BILLING_DUNNING_DAYS if days_elapsed >= day)


def _run_dunning_impl() -> dict[str, int]:
    reminded = 0
    expired = 0
    canceled = 0
    now = get_datetime_utc()

    with Session(engine) as session:
        past_due = list(
            session.exec(
                select(BillingSubscription).where(
                    BillingSubscription.status == SubscriptionStatus.past_due
                )
            ).all()
        )
        for sub in past_due:
            if sub.past_due_since is None:
                # Shouldn't happen — ``transition`` stamps it on entry — but a
                # row that got here another way still deserves a window rather
                # than being expired immediately.
                sub.past_due_since = now
                sub.grace_expires_at = now + timedelta(
                    days=settings.BILLING_GRACE_PERIOD_DAYS
                )
                session.add(sub)
                session.commit()

            if sub.grace_expires_at is not None and now >= sub.grace_expires_at:
                if transition(session, sub, "grace_expired"):
                    expired += 1
                    logger.info(
                        "Grace period expired for subscription %s (%s) — now on "
                        "Free limits",
                        sub.id,
                        sub.tier.value,
                    )
                    send_billing_email(session, sub, "grace_expired")
                continue

            days_elapsed = (now - sub.past_due_since).days
            due = _due_stage(days_elapsed)
            if due > sub.dunning_stage:
                # Send one reminder per run even if several are notionally due
                # (a worker that was down for a week should not deliver four
                # emails at once), then record the full stage so the backlog is
                # not replayed tomorrow either.
                sub.dunning_stage = due
                session.add(sub)
                session.commit()
                send_billing_email(session, sub, "payment_failed")
                reminded += 1

        pending = list(
            session.exec(
                select(BillingSubscription).where(
                    BillingSubscription.status
                    == SubscriptionStatus.pending_cancellation
                )
            ).all()
        )
        for sub in pending:
            if sub.period_end is not None and now >= sub.period_end:
                if transition(session, sub, "period_ended"):
                    apply_tier(session, sub, DEFAULT_TIER)
                    session.commit()
                    send_billing_email(session, sub, "subscription_canceled")
                    canceled += 1

    if reminded or expired or canceled:
        logger.info(
            "Dunning: %d reminder(s), %d grace expiry(ies), %d cancellation(s)",
            reminded,
            expired,
            canceled,
        )
    return {"reminded": reminded, "expired": expired, "canceled": canceled}


@celery_app.task(name="billing.run_dunning", bind=True)
def run_dunning(self: object) -> dict[str, int]:  # noqa: ARG001
    return _run_dunning_impl()


def _run_quota_warnings_impl() -> dict[str, int]:
    """Email owners who have crossed 80% or 100% of a meter this period.

    Only for accounts in good standing — an account already past due is
    getting dunning mail, and "you are near your limit" stacked on top of "we
    could not take your payment" is noise.

    One warning per period per account, at the highest threshold crossed:
    ``quota_warning_percent`` records it and the period rollover clears it.
    """
    sent = 0
    with Session(engine) as session:
        subs = list(
            session.exec(
                select(BillingSubscription).where(
                    col(BillingSubscription.status).in_(
                        [SubscriptionStatus.active, SubscriptionStatus.trialing]
                    )
                )
            ).all()
        )
        for sub in subs:
            user = session.get(User, sub.user_id)
            if user is None or user.is_superuser:
                continue
            sub = ensure_current_period(session, sub)
            limits = limits_for(effective_tier(sub))
            used_by_meter = {
                "analyses": period_usage(
                    session,
                    user.id,
                    UsageMeter.analyses,
                    sub.period_start,
                    sub.period_end,
                ),
                "fixes": period_usage(
                    session,
                    user.id,
                    UsageMeter.fixes,
                    sub.period_start,
                    sub.period_end,
                ),
                "repos": len(enabled_repo_ids(session, user.id)),
            }

            for meter_name, used in used_by_meter.items():
                limit = limits.get(meter_name)
                if not limit:
                    # Unlimited, or a zero allowance that no amount of usage
                    # can be a percentage of.
                    continue
                percent = int(used * 100 / limit)
                crossed = [t for t in _WARN_THRESHOLDS if percent >= t]
                if not crossed:
                    continue
                highest = max(crossed)
                if sub.quota_warning_percent >= highest:
                    continue
                # Recorded before sending: a send that fails is not worth
                # re-attempting every day for the rest of the month.
                sub.quota_warning_percent = highest
                session.add(sub)
                session.commit()
                if send_quota_warning(session, sub, meter_name, used, limit, highest):
                    sent += 1
                break

    if sent:
        logger.info("Quota warnings: %d email(s) sent", sent)
    return {"sent": sent}


@celery_app.task(name="billing.run_quota_warnings", bind=True)
def run_quota_warnings(self: object) -> dict[str, int]:  # noqa: ARG001
    return _run_quota_warnings_impl()
