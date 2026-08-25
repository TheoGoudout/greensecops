"""Subscription lifecycle: periods, entitlement, and transitions.

Three responsibilities, all of them answers to "what is this account allowed to
do *right now*":

* **Periods** — every metered allowance is scoped to a billing period, so
  something has to roll that window forward. Stripe drives it for paying tiers;
  a calendar month is the fallback for tiers Stripe never touches.
* **Entitlement** — ``effective_tier`` collapses (tier, status) into the single
  tier that quota enforcement should apply. It is the only place the grace
  policy is expressed.
* **Transitions** — thin wrappers over ``BillingSubscriptionMachine`` that also
  maintain the columns a transition implies (grace deadlines, dunning stage)
  and emit the transition's declared SSE signal.
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from app.core.config import settings
from app.core.plans import DEFAULT_TIER
from app.models import (
    BillingSubscription,
    SubscriptionStatus,
    User,
    UserTier,
    get_datetime_utc,
)
from app.services import state_machines as sm
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev

from .owner import billing_owner_org_ids

logger = logging.getLogger(__name__)


# ─── Entitlement ─────────────────────────────────────────────────────────────


def effective_tier(sub: BillingSubscription | None) -> UserTier:
    """The tier whose limits actually apply to ``sub`` right now.

    This is where the grace policy lives, and it is deliberately the *only*
    place: a subscription in ``past_due`` keeps every bit of its paid plan
    while the dunning reminders go out, and only once ``grace_expired`` has
    moved it to ``unpaid`` does it fall back to Free. ``canceled`` is the same
    fallback by a different route.

    Nothing here deletes or hides data — an account on Free limits keeps all of
    its history and gets its plan back the moment a payment succeeds.
    """
    if sub is None:
        return DEFAULT_TIER
    if sub.status in sm.ENTITLED_STATUSES:
        return sub.tier
    return DEFAULT_TIER


def is_downgraded(sub: BillingSubscription | None) -> bool:
    """Whether the account is being limited below what it bought."""
    return sub is not None and effective_tier(sub) != sub.tier


# ─── Subscription access ─────────────────────────────────────────────────────


def get_subscription(
    session: Session, user_id: uuid.UUID
) -> BillingSubscription | None:
    return session.exec(
        select(BillingSubscription).where(BillingSubscription.user_id == user_id)
    ).first()


def get_or_create_subscription(session: Session, user: User) -> BillingSubscription:
    """Fetch ``user``'s subscription, creating an active free one if absent.

    Seeded from ``user.tier`` rather than hard-coded to free. The old version
    always wrote ``UserTier.free`` here, so an account whose tier had been set
    directly (an operator granting open_source, a fixture) got its quota from
    ``User.tier`` and its billing page from ``BillingSubscription.tier`` — two
    different answers to the same question. The subscription is the authority
    now; ``User.tier`` is a mirror kept in sync by ``apply_tier``.
    """
    sub = get_subscription(session, user.id)
    if sub is not None:
        return sub
    sub = BillingSubscription(
        user_id=user.id,
        tier=user.tier or DEFAULT_TIER,
        status=SubscriptionStatus.active,
    )
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub


def apply_tier(session: Session, sub: BillingSubscription, tier: UserTier) -> None:
    """Set the purchased tier on the subscription and mirror it onto the user.

    ``User.tier`` is denormalised for cheap reads (badges, admin lists). Every
    write to it goes through here so the mirror cannot drift from its source.
    """
    sub.tier = tier
    session.add(sub)
    user = session.get(User, sub.user_id)
    if user is not None:
        user.tier = tier
        session.add(user)


# ─── Billing periods ─────────────────────────────────────────────────────────


def month_bounds(now: datetime) -> tuple[datetime, datetime]:
    """UTC calendar-month bounds containing ``now``: [start, end)."""
    start = now.replace(hour=0, minute=0, second=0, microsecond=0, day=1)
    end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    return start, end


def ensure_current_period(
    session: Session, sub: BillingSubscription
) -> BillingSubscription:
    """Roll ``sub`` onto the current billing period if the previous one ended.

    A Stripe-paying tier's ``period_end`` is kept current by the webhook (which
    reads the subscription item's ``current_period_end``); this calendar-month
    rollover is the fallback for tiers with no Stripe cycle (free, open_source)
    and for a brand-new subscription no webhook has touched yet.

    Rolling the window is now the whole job. The previous implementation also
    had to snapshot a ``fixes_used_baseline`` here, because fix usage was
    derived from a lifetime counter and the only way to scope it to a period
    was to subtract where the last one ended. The ledger records when each unit
    was consumed, so a period is just a date range.
    """
    now = get_datetime_utc()
    if sub.period_end is not None and now < sub.period_end:
        return sub
    sub.period_start, sub.period_end = month_bounds(now)
    # A fresh allowance deserves fresh warnings: without this, an account that
    # hit 100% in March would never be warned again.
    sub.quota_warning_percent = 0
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub


def set_stripe_period(
    sub: BillingSubscription, start_ts: int | None, end_ts: int | None
) -> None:
    """Adopt Stripe's billing cycle as the usage period.

    A paid tier's allowance should reset when it is actually re-billed, not on
    the first of the month.
    """
    if start_ts is None or end_ts is None:
        return
    sub.period_start = datetime.fromtimestamp(start_ts, tz=timezone.utc)
    sub.period_end = datetime.fromtimestamp(end_ts, tz=timezone.utc)


# ─── Transitions ─────────────────────────────────────────────────────────────


def _publish(session: Session, sub: BillingSubscription, event: str) -> None:
    """Emit the transition's declared SSE output to every org it affects.

    SSE is routed by org while a subscription belongs to a user, so a user who
    is the billing owner of three orgs gets the signal on all three — each of
    those dashboards is showing limits that just changed.
    """
    signal = sm.output_for(sm.BillingSubscriptionMachine, event)
    if signal is None:
        return
    for org_id in billing_owner_org_ids(session, sub.user_id):
        events_pub.publish_event(
            ev.subscription_changed(
                str(org_id), signal, sub.tier.value, sub.status.value
            )
        )


def transition(session: Session, sub: BillingSubscription, event: str) -> bool:
    """Fire ``event`` if legal, maintain the columns it implies, and publish.

    Uses ``try_advance`` rather than ``advance`` because almost every caller is
    a Stripe webhook, and Stripe redelivers and reorders events exactly like
    GitHub does. A ``payment_failed`` arriving twice must be a no-op, not a
    crash — and must not restart the grace window, which is why the deadline is
    only stamped on a transition that actually fired.
    """
    fired = sm.try_advance(sub, sm.BillingSubscriptionMachine, event)
    if not fired:
        logger.debug(
            "Billing transition %r not legal from %s (subscription %s) — ignored",
            event,
            sub.status,
            sub.id,
        )
        return False

    now = get_datetime_utc()
    if sub.status == SubscriptionStatus.past_due:
        # Only stamp on entry, so a second failed invoice inside an open window
        # does not hand the user a fresh 14 days.
        if sub.past_due_since is None:
            sub.past_due_since = now
            sub.grace_expires_at = now + timedelta(
                days=settings.BILLING_GRACE_PERIOD_DAYS
            )
            sub.dunning_stage = 0
    elif sub.status == SubscriptionStatus.active:
        # Recovered: clear the whole dunning state so a future failure starts
        # a clean window rather than inheriting this one's remaining days.
        sub.past_due_since = None
        sub.grace_expires_at = None
        sub.dunning_stage = 0
        sub.cancel_at_period_end = False
    elif sub.status == SubscriptionStatus.pending_cancellation:
        sub.cancel_at_period_end = True
    elif sub.status == SubscriptionStatus.canceled:
        sub.canceled_at = now
        sub.cancel_at_period_end = False

    session.add(sub)
    session.commit()
    session.refresh(sub)
    _publish(session, sub, event)
    return True


def grace_remaining_days(sub: BillingSubscription, now: datetime | None = None) -> int:
    """Days left in the grace window; 0 once it has closed.

    Rounded **up**, deliberately. ``timedelta.days`` truncates, so a deadline
    23 hours away would be reported as "0 days" — and a deadline nine days out
    as eight. The frontend's countdown uses ``Math.ceil`` for the same reason,
    and the two have to agree: a dunning email saying eight days beside a
    banner saying nine is the kind of discrepancy that costs a support ticket.
    """
    if sub.grace_expires_at is None:
        return 0
    delta = sub.grace_expires_at - (now or get_datetime_utc())
    if delta.total_seconds() <= 0:
        return 0
    return math.ceil(delta.total_seconds() / 86_400)
