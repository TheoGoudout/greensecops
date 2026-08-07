"""The subscription lifecycle: transitions, entitlement, periods."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlmodel import Session

from app.core.config import settings
from app.models import SubscriptionStatus, UserTier
from app.services import state_machines as sm
from app.services.billing import lifecycle
from tests.utils.billing import make_subscription, make_user, owned_setup


class _Row:
    """A bare object with a ``status`` column, for pure graph assertions."""

    def __init__(self, status: SubscriptionStatus) -> None:
        self.status = status


# ─── The state graph ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("start", "event", "expected"),
    [
        (
            SubscriptionStatus.incomplete,
            "checkout_completed",
            SubscriptionStatus.active,
        ),
        (SubscriptionStatus.incomplete, "trial_started", SubscriptionStatus.trialing),
        (
            SubscriptionStatus.incomplete,
            "subscription_deleted",
            SubscriptionStatus.canceled,
        ),
        (SubscriptionStatus.trialing, "trial_converted", SubscriptionStatus.active),
        (SubscriptionStatus.trialing, "trial_ended", SubscriptionStatus.past_due),
        (SubscriptionStatus.active, "payment_failed", SubscriptionStatus.past_due),
        (
            SubscriptionStatus.active,
            "cancel_requested",
            SubscriptionStatus.pending_cancellation,
        ),
        (SubscriptionStatus.past_due, "payment_succeeded", SubscriptionStatus.active),
        (SubscriptionStatus.past_due, "grace_expired", SubscriptionStatus.unpaid),
        (SubscriptionStatus.unpaid, "payment_succeeded", SubscriptionStatus.active),
        (
            SubscriptionStatus.pending_cancellation,
            "resumed",
            SubscriptionStatus.active,
        ),
        (
            SubscriptionStatus.pending_cancellation,
            "period_ended",
            SubscriptionStatus.canceled,
        ),
    ],
)
def test_legal_transitions(
    start: SubscriptionStatus, event: str, expected: SubscriptionStatus
) -> None:
    row = _Row(start)
    assert sm.advance(row, sm.BillingSubscriptionMachine, event) == expected


@pytest.mark.parametrize(
    ("start", "event"),
    [
        # Cannot skip the grace window: a healthy subscription is not expirable.
        (SubscriptionStatus.active, "grace_expired"),
        # Cannot fail a payment that was never taken.
        (SubscriptionStatus.incomplete, "payment_failed"),
        # Cannot pay your way out of a state that never owed anything.
        (SubscriptionStatus.active, "payment_succeeded"),
        # Terminal is terminal.
        (SubscriptionStatus.canceled, "payment_succeeded"),
        (SubscriptionStatus.canceled, "resumed"),
        # Grace expiry happens once.
        (SubscriptionStatus.unpaid, "grace_expired"),
    ],
)
def test_illegal_transitions_are_refused(start: SubscriptionStatus, event: str) -> None:
    row = _Row(start)
    assert sm.try_advance(row, sm.BillingSubscriptionMachine, event) is False
    assert row.status == start


def test_every_event_declares_an_sse_output() -> None:
    """A silent transition would leave the UI showing a stale plan."""
    machine = sm.BillingSubscriptionMachine
    events = {t.event for state in machine.states for t in state.transitions}
    for event in events:
        assert machine.outputs.get(event) is not None, event


# ─── Entitlement ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "entitled"),
    [
        (SubscriptionStatus.active, True),
        (SubscriptionStatus.trialing, True),
        # The grace window keeps the paid plan working in full.
        (SubscriptionStatus.past_due, True),
        (SubscriptionStatus.pending_cancellation, True),
        (SubscriptionStatus.unpaid, False),
        (SubscriptionStatus.canceled, False),
        (SubscriptionStatus.incomplete, False),
    ],
)
def test_effective_tier_applies_the_grace_policy(
    db: Session, status: SubscriptionStatus, entitled: bool
) -> None:
    user = make_user(db, tier=UserTier.pro)
    sub = make_subscription(db, user, tier=UserTier.pro, status=status)
    expected = UserTier.pro if entitled else UserTier.free
    assert lifecycle.effective_tier(sub) == expected
    assert lifecycle.is_downgraded(sub) is not entitled


def test_effective_tier_of_no_subscription_is_free(db: Session) -> None:
    assert lifecycle.effective_tier(None) == UserTier.free


# ─── Transitions maintain their columns ──────────────────────────────────────


def test_payment_failure_opens_a_grace_window(db: Session) -> None:
    user, _org, _repo = owned_setup(db, tier=UserTier.pro)
    sub = lifecycle.get_or_create_subscription(db, user)

    assert lifecycle.transition(db, sub, "payment_failed") is True
    assert sub.status == SubscriptionStatus.past_due
    assert sub.past_due_since is not None
    assert sub.grace_expires_at is not None
    expected = sub.past_due_since + timedelta(days=settings.BILLING_GRACE_PERIOD_DAYS)
    assert abs((sub.grace_expires_at - expected).total_seconds()) < 1


def test_a_second_failure_does_not_extend_the_window(db: Session) -> None:
    """Otherwise a card failing weekly would never actually expire."""
    user, _org, _repo = owned_setup(db, tier=UserTier.pro)
    sub = lifecycle.get_or_create_subscription(db, user)
    lifecycle.transition(db, sub, "payment_failed")
    first_deadline = sub.grace_expires_at

    # Redelivered or simply a second failed invoice inside the same window.
    lifecycle.transition(db, sub, "payment_failed")
    assert sub.grace_expires_at == first_deadline


def test_recovery_clears_all_dunning_state(db: Session) -> None:
    """A future failure gets a clean window, not this one's leftovers."""
    user, _org, _repo = owned_setup(db, tier=UserTier.pro)
    sub = lifecycle.get_or_create_subscription(db, user)
    lifecycle.transition(db, sub, "payment_failed")
    sub.dunning_stage = 3
    db.add(sub)
    db.commit()

    assert lifecycle.transition(db, sub, "payment_succeeded") is True
    assert sub.status == SubscriptionStatus.active
    assert sub.past_due_since is None
    assert sub.grace_expires_at is None
    assert sub.dunning_stage == 0


def test_illegal_transition_is_a_no_op_not_a_crash(db: Session) -> None:
    """Stripe redelivers and reorders; a handler must survive both."""
    user, _org, _repo = owned_setup(db)
    sub = lifecycle.get_or_create_subscription(db, user)
    assert lifecycle.transition(db, sub, "grace_expired") is False
    assert sub.status == SubscriptionStatus.active


def test_cancellation_marks_the_period_end_flag(db: Session) -> None:
    user, _org, _repo = owned_setup(db, tier=UserTier.pro)
    sub = lifecycle.get_or_create_subscription(db, user)
    assert lifecycle.transition(db, sub, "cancel_requested") is True
    assert sub.cancel_at_period_end is True
    # Still entitled: they paid through the end of the period.
    assert lifecycle.effective_tier(sub) == UserTier.pro

    assert lifecycle.transition(db, sub, "period_ended") is True
    assert sub.status == SubscriptionStatus.canceled
    assert sub.canceled_at is not None
    assert sub.cancel_at_period_end is False


def test_grace_remaining_days_floors_at_zero(db: Session) -> None:
    user = make_user(db)
    sub = make_subscription(db, user)
    sub.grace_expires_at = datetime.now(timezone.utc) - timedelta(days=3)
    assert lifecycle.grace_remaining_days(sub) == 0


# ─── Subscription creation and tier mirroring ────────────────────────────────


def test_subscription_is_seeded_from_the_users_tier(db: Session) -> None:
    """The bug this fixes: quota read User.tier, the billing page read sub.tier.

    An operator granting open_source by setting the column directly used to get
    an account metered as open_source but displayed as Free.
    """
    user = make_user(db, tier=UserTier.open_source)
    sub = lifecycle.get_or_create_subscription(db, user)
    assert sub.tier == UserTier.open_source
    assert sub.status == SubscriptionStatus.active


def test_apply_tier_mirrors_onto_the_user(db: Session) -> None:
    user = make_user(db)
    sub = lifecycle.get_or_create_subscription(db, user)
    lifecycle.apply_tier(db, sub, UserTier.pro)
    db.commit()
    db.refresh(user)
    assert sub.tier == UserTier.pro
    assert user.tier == UserTier.pro


# ─── Periods ─────────────────────────────────────────────────────────────────


def test_month_bounds_wrap_the_year(db: Session) -> None:
    start, end = lifecycle.month_bounds(datetime(2026, 12, 15, tzinfo=timezone.utc))
    assert start == datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert end == datetime(2027, 1, 1, tzinfo=timezone.utc)


def test_period_rolls_over_and_resets_quota_warnings(db: Session) -> None:
    """A fresh allowance deserves fresh warnings."""
    user = make_user(db)
    sub = make_subscription(
        db,
        user,
        period_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
        period_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    sub.quota_warning_percent = 100
    db.add(sub)
    db.commit()

    with patch.object(
        lifecycle,
        "get_datetime_utc",
        return_value=datetime(2026, 7, 5, tzinfo=timezone.utc),
    ):
        rolled = lifecycle.ensure_current_period(db, sub)
    assert rolled.period_start == datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert rolled.period_end == datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert rolled.quota_warning_percent == 0


def test_period_is_left_alone_mid_cycle(db: Session) -> None:
    user = make_user(db)
    sub = make_subscription(
        db,
        user,
        period_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
        period_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    with patch.object(
        lifecycle,
        "get_datetime_utc",
        return_value=datetime(2026, 6, 15, tzinfo=timezone.utc),
    ):
        unchanged = lifecycle.ensure_current_period(db, sub)
    assert unchanged.period_end == datetime(2026, 7, 1, tzinfo=timezone.utc)


def test_stripe_period_overrides_the_calendar_month(db: Session) -> None:
    """A paid plan's allowance resets when it is re-billed, not on the 1st."""
    user = make_user(db)
    sub = make_subscription(db, user)
    start = int(datetime(2026, 6, 17, tzinfo=timezone.utc).timestamp())
    end = int(datetime(2026, 7, 17, tzinfo=timezone.utc).timestamp())
    lifecycle.set_stripe_period(sub, start, end)
    assert sub.period_start == datetime(2026, 6, 17, tzinfo=timezone.utc)
    assert sub.period_end == datetime(2026, 7, 17, tzinfo=timezone.utc)


def test_stripe_period_ignores_a_missing_bound(db: Session) -> None:
    user = make_user(db)
    sub = make_subscription(db, user)
    lifecycle.set_stripe_period(sub, None, None)
    assert sub.period_start is None


def test_grace_days_round_up_to_match_the_ui(db: Session) -> None:
    """``timedelta.days`` truncates; a deadline 23 hours out is not "0 days".

    The frontend countdown uses ``Math.ceil``, so the backend must too — an
    email saying eight days beside a banner saying nine is a support ticket.
    """
    user = make_user(db)
    sub = make_subscription(db, user)
    now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)

    sub.grace_expires_at = now + timedelta(days=9)
    assert lifecycle.grace_remaining_days(sub, now) == 9

    sub.grace_expires_at = now + timedelta(hours=23)
    assert lifecycle.grace_remaining_days(sub, now) == 1

    sub.grace_expires_at = now + timedelta(minutes=1)
    assert lifecycle.grace_remaining_days(sub, now) == 1
