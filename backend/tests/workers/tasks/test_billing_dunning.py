"""Dunning: the schedule of reminders, and the grace expiry at the end of it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session

from app.core.config import settings
from app.models import SubscriptionStatus, UserTier
from app.workers.tasks import billing as billing_task
from tests.utils.billing import make_subscription, owned_setup


def _past_due(db: Session, *, days_ago: int, stage: int = 0):  # type: ignore[no-untyped-def]
    """A subscription that entered ``past_due`` ``days_ago`` days ago."""
    user, _org, _repo = owned_setup(db, tier=UserTier.pro)
    sub = make_subscription(
        db, user, tier=UserTier.pro, status=SubscriptionStatus.past_due
    )
    now = datetime.now(timezone.utc)
    sub.past_due_since = now - timedelta(days=days_ago)
    sub.grace_expires_at = sub.past_due_since + timedelta(
        days=settings.BILLING_GRACE_PERIOD_DAYS
    )
    sub.dunning_stage = stage
    db.add(sub)
    db.commit()
    return sub


# ─── The reminder schedule ───────────────────────────────────────────────────


def test_due_stage_counts_elapsed_reminder_days() -> None:
    """Days 0/3/7/13 by default, so day 8 means three reminders are owed."""
    assert billing_task._due_stage(0) == 1
    assert billing_task._due_stage(2) == 1
    assert billing_task._due_stage(3) == 2
    assert billing_task._due_stage(8) == 3
    assert billing_task._due_stage(13) == 4
    # Past the last scheduled day, nothing more is owed.
    assert billing_task._due_stage(30) == 4


def test_first_reminder_is_sent_and_recorded(db: Session) -> None:
    sub = _past_due(db, days_ago=0)
    with patch.object(billing_task, "send_billing_email", return_value=True) as send:
        result = billing_task._run_dunning_impl()
    assert result["reminded"] >= 1
    db.refresh(sub)
    assert sub.dunning_stage == 1
    kinds = [call.args[2] for call in send.call_args_list]
    assert "payment_failed" in kinds


def test_a_second_run_the_same_day_sends_nothing(db: Session) -> None:
    """The property that makes the task safe to re-run.

    A beat firing twice, a worker restarting mid-pass, or an operator running
    it by hand must not re-send yesterday's reminder.
    """
    sub = _past_due(db, days_ago=0)
    with patch.object(billing_task, "send_billing_email", return_value=True):
        billing_task._run_dunning_impl()
    db.refresh(sub)
    first_stage = sub.dunning_stage

    with patch.object(billing_task, "send_billing_email", return_value=True) as send:
        billing_task._run_dunning_impl()
    db.refresh(sub)
    assert sub.dunning_stage == first_stage
    assert send.call_count == 0


def test_a_backlog_delivers_one_email_not_four(db: Session) -> None:
    """A worker down for a week should not flood the user on its return."""
    sub = _past_due(db, days_ago=13, stage=0)
    with patch.object(billing_task, "send_billing_email", return_value=True) as send:
        billing_task._run_dunning_impl()
    db.refresh(sub)
    # Every reminder is *recorded* as delivered so the backlog is not replayed,
    # but only one actually goes out.
    assert sub.dunning_stage == 4
    assert send.call_count == 1


# ─── Grace expiry ────────────────────────────────────────────────────────────


def test_grace_expiry_moves_to_unpaid(db: Session) -> None:
    sub = _past_due(db, days_ago=settings.BILLING_GRACE_PERIOD_DAYS + 1, stage=4)
    with patch.object(billing_task, "send_billing_email", return_value=True) as send:
        result = billing_task._run_dunning_impl()
    assert result["expired"] >= 1
    db.refresh(sub)
    assert sub.status == SubscriptionStatus.unpaid
    # The purchased tier is untouched — this is a limit change, not a refund.
    assert sub.tier == UserTier.pro
    kinds = [call.args[2] for call in send.call_args_list]
    assert "grace_expired" in kinds


def test_inside_the_window_nothing_expires(db: Session) -> None:
    sub = _past_due(db, days_ago=settings.BILLING_GRACE_PERIOD_DAYS - 1, stage=4)
    with patch.object(billing_task, "send_billing_email", return_value=True):
        billing_task._run_dunning_impl()
    db.refresh(sub)
    assert sub.status == SubscriptionStatus.past_due


def test_expiry_is_not_repeated(db: Session) -> None:
    """``unpaid`` is not ``past_due``, so the next run skips it entirely."""
    sub = _past_due(db, days_ago=settings.BILLING_GRACE_PERIOD_DAYS + 5, stage=4)
    with patch.object(billing_task, "send_billing_email", return_value=True):
        billing_task._run_dunning_impl()
    db.refresh(sub)
    assert sub.status == SubscriptionStatus.unpaid

    with patch.object(billing_task, "send_billing_email", return_value=True) as send:
        result = billing_task._run_dunning_impl()
    assert result["expired"] == 0
    assert send.call_count == 0


def test_a_past_due_row_with_no_deadline_gets_a_window(db: Session) -> None:
    """Defensive: never expire an account that was never given its days."""
    user, _org, _repo = owned_setup(db, tier=UserTier.pro)
    sub = make_subscription(
        db, user, tier=UserTier.pro, status=SubscriptionStatus.past_due
    )
    assert sub.past_due_since is None

    with patch.object(billing_task, "send_billing_email", return_value=True):
        billing_task._run_dunning_impl()
    db.refresh(sub)
    assert sub.status == SubscriptionStatus.past_due
    assert sub.grace_expires_at is not None


# ─── Cancellation at period end ──────────────────────────────────────────────


def test_cancellation_finalises_once_the_period_ends(db: Session) -> None:
    user, _org, _repo = owned_setup(db, tier=UserTier.pro)
    sub = make_subscription(
        db,
        user,
        tier=UserTier.pro,
        status=SubscriptionStatus.pending_cancellation,
        period_start=datetime.now(timezone.utc) - timedelta(days=40),
        period_end=datetime.now(timezone.utc) - timedelta(days=1),
    )
    with patch.object(billing_task, "send_billing_email", return_value=True) as send:
        result = billing_task._run_dunning_impl()
    assert result["canceled"] >= 1
    db.refresh(sub)
    assert sub.status == SubscriptionStatus.canceled
    assert sub.tier == UserTier.free
    kinds = [call.args[2] for call in send.call_args_list]
    assert "subscription_canceled" in kinds


def test_cancellation_waits_for_the_period_end(db: Session) -> None:
    """They paid for the month; they keep the month."""
    user, _org, _repo = owned_setup(db, tier=UserTier.pro)
    sub = make_subscription(
        db,
        user,
        tier=UserTier.pro,
        status=SubscriptionStatus.pending_cancellation,
        period_end=datetime.now(timezone.utc) + timedelta(days=10),
    )
    with patch.object(billing_task, "send_billing_email", return_value=True):
        billing_task._run_dunning_impl()
    db.refresh(sub)
    assert sub.status == SubscriptionStatus.pending_cancellation
    assert sub.tier == UserTier.pro


# ─── Quota warnings ──────────────────────────────────────────────────────────


def test_quota_warning_fires_at_eighty_percent(db: Session) -> None:
    from app.models import UsageMeter
    from tests.utils.billing import record_usage

    user, org, _repo = owned_setup(db)
    sub = billing_task.ensure_current_period(db, make_subscription(db, user))
    # Free allows 100 analyses; 85 crosses the 80% threshold but not 100%.
    for _ in range(85):
        record_usage(db, user, org, meter=UsageMeter.analyses)

    with patch.object(billing_task, "send_quota_warning", return_value=True) as warn:
        result = billing_task._run_quota_warnings_impl()
    assert result["sent"] >= 1
    db.refresh(sub)
    assert sub.quota_warning_percent == 80
    assert warn.call_args.args[2] == "analyses"


def test_quota_warning_is_sent_once_per_period(db: Session) -> None:
    from app.models import UsageMeter
    from tests.utils.billing import record_usage

    user, org, _repo = owned_setup(db)
    make_subscription(db, user)
    for _ in range(85):
        record_usage(db, user, org, meter=UsageMeter.analyses)

    with patch.object(billing_task, "send_quota_warning", return_value=True):
        billing_task._run_quota_warnings_impl()
    with patch.object(billing_task, "send_quota_warning", return_value=True) as warn:
        billing_task._run_quota_warnings_impl()
    assert warn.call_count == 0


def test_past_due_accounts_get_no_quota_warning(db: Session) -> None:
    """They are already receiving dunning mail; this would only be noise."""
    from app.models import UsageMeter
    from tests.utils.billing import record_usage

    user, org, _repo = owned_setup(db)
    make_subscription(db, user, status=SubscriptionStatus.past_due)
    for _ in range(150):
        record_usage(db, user, org, meter=UsageMeter.analyses)

    with patch.object(billing_task, "send_quota_warning", return_value=True) as warn:
        billing_task._run_quota_warnings_impl()
    assert warn.call_count == 0
