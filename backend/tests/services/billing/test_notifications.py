"""Billing emails: that they render, and that they say the right numbers.

The templates are the user-facing half of the grace policy. A dunning email
that fails to say "your plan is still working" or gets the deadline wrong is
the difference between a user updating their card and a user assuming they have
already been cut off.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlmodel import Session

from app.core.config import settings
from app.models import Invoice, InvoiceStatus, SubscriptionStatus, UserTier
from app.services.billing import notifications
from tests.utils.billing import make_subscription, make_user, owned_setup


@pytest.fixture
def emails_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend SMTP is configured; the send itself is always patched out."""
    monkeypatch.setattr(type(settings), "emails_enabled", property(lambda _self: True))


def _captured(send) -> tuple[str, str, str]:  # type: ignore[no-untyped-def]
    kwargs = send.call_args.kwargs
    return kwargs["email_to"], kwargs["subject"], kwargs["html_content"]


# ─── The guard ───────────────────────────────────────────────────────────────


def test_nothing_is_sent_when_mail_is_unconfigured(db: Session) -> None:
    """Dev, CI and self-hosted installs stay silent without any caller knowing."""
    user = make_user(db)
    sub = make_subscription(db, user)
    with patch.object(notifications, "send_email") as send:
        assert (
            notifications.send_billing_email(db, sub, "subscription_started") is False
        )
    assert send.call_count == 0


def test_an_unknown_kind_is_refused_not_raised(db: Session, emails_on: None) -> None:
    user = make_user(db)
    sub = make_subscription(db, user)
    with patch.object(notifications, "send_email") as send:
        assert notifications.send_billing_email(db, sub, "not_a_template") is False
    assert send.call_count == 0


# ─── Every template renders ──────────────────────────────────────────────────


@pytest.mark.parametrize("kind", sorted(notifications._TEMPLATES))
def test_every_template_renders_without_leftover_placeholders(
    db: Session, emails_on: None, kind: str
) -> None:
    """A missing context key would ship "{{ plan_name }}" to a paying customer."""
    user, _org, _repo = owned_setup(db, tier=UserTier.pro)
    sub = make_subscription(
        db, user, tier=UserTier.pro, status=SubscriptionStatus.past_due
    )
    sub.grace_expires_at = datetime.now(timezone.utc) + timedelta(days=9)
    db.add(sub)
    db.commit()

    extra: dict[str, object] = {}
    if kind == "quota_warning":
        extra = {
            "meter_label": "analyses",
            "used": "8,000",
            "limit": "10,000",
            "percent": 80,
            "resets_at": "1 September 2026",
            "upgrade_hint": "Upgrade to Ultimate for unlimited analyses.",
        }

    with patch.object(notifications, "send_email") as send:
        assert notifications.send_billing_email(db, sub, kind, **extra) is True
    _to, subject, html = _captured(send)
    assert "{{" not in html
    assert "{{" not in subject
    assert "Undefined" not in html


# ─── The dunning email says the right things ─────────────────────────────────


def test_dunning_email_leads_with_what_still_works(
    db: Session, emails_on: None
) -> None:
    user, _org, _repo = owned_setup(db, tier=UserTier.pro)
    sub = make_subscription(
        db, user, tier=UserTier.pro, status=SubscriptionStatus.past_due
    )
    sub.grace_expires_at = datetime.now(timezone.utc) + timedelta(days=9)
    db.add(sub)
    db.commit()

    invoice = Invoice(
        subscription_id=sub.id,
        stripe_invoice_id="in_test_1",
        status=InvoiceStatus.open,
        amount_due_cents=7900,
        currency="usd",
        hosted_invoice_url="https://invoice.stripe.com/i/abc",
    )
    db.add(invoice)
    db.commit()

    with patch.object(notifications, "send_email") as send:
        notifications.send_billing_email(db, sub, "payment_failed", invoice=invoice)
    to, subject, html = _captured(send)

    assert to == user.email
    # The reassurance is the point: an alarming email that omits it makes users
    # assume they have already been cut off.
    assert "Nothing has changed yet" in html
    assert "all your data is intact" in html
    # The deadline, the amount, and a link to the thing that needs paying.
    assert "9 day(s)" in html
    assert "$79.00" in html
    assert "https://invoice.stripe.com/i/abc" in html
    assert "9 day(s)" in subject


def test_grace_expired_email_states_the_new_limits_and_the_way_back(
    db: Session, emails_on: None
) -> None:
    user, _org, _repo = owned_setup(db, tier=UserTier.pro)
    sub = make_subscription(
        db, user, tier=UserTier.pro, status=SubscriptionStatus.unpaid
    )
    with patch.object(notifications, "send_email") as send:
        notifications.send_billing_email(db, sub, "grace_expired")
    _to, _subject, html = _captured(send)

    # What they now have, in numbers, not "reduced limits".
    assert "10,000" in html or "1,000" in html
    # And, crucially, that nothing was destroyed.
    assert "have been removed" in html
    assert "Restore your plan" in html


def test_invoice_paid_is_a_receipt(db: Session, emails_on: None) -> None:
    user, _org, _repo = owned_setup(db, tier=UserTier.starter)
    sub = make_subscription(db, user, tier=UserTier.starter)
    invoice = Invoice(
        subscription_id=sub.id,
        stripe_invoice_id="in_test_2",
        status=InvoiceStatus.paid,
        amount_due_cents=1900,
        amount_paid_cents=1900,
        currency="usd",
        period_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
        period_end=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    db.add(invoice)
    db.commit()

    with patch.object(notifications, "send_email") as send:
        notifications.send_billing_email(db, sub, "invoice_paid", invoice=invoice)
    _to, _subject, html = _captured(send)
    assert "$19.00" in html
    assert "1 August 2026" in html
    assert "1 September 2026" in html


# ─── Quota warnings ──────────────────────────────────────────────────────────


def test_quota_warning_names_the_plan_that_raises_this_meter(
    db: Session, emails_on: None
) -> None:
    """A hint pointing at a plan with the same cap would be worse than none."""
    user, _org, _repo = owned_setup(db, tier=UserTier.starter)
    sub = make_subscription(db, user, tier=UserTier.starter)

    with patch.object(notifications, "send_email") as send:
        assert notifications.send_quota_warning(db, sub, "fixes", 80, 100, 80) is True
    _to, subject, html = _captured(send)
    assert "80%" in subject
    assert "AI fix generations" in html
    assert "Pro" in html
    assert "1,000" in html


def test_quota_warning_on_an_unlimited_plan_points_at_support(
    db: Session, emails_on: None
) -> None:
    user, _org, _repo = owned_setup(db, tier=UserTier.ultimate)
    sub = make_subscription(db, user, tier=UserTier.ultimate)
    with patch.object(notifications, "send_email") as send:
        notifications.send_quota_warning(db, sub, "analyses", 10, 10, 100)
    _to, _subject, html = _captured(send)
    assert "Contact support" in html


# ─── Formatting helpers ──────────────────────────────────────────────────────


def test_money_is_formatted_from_minor_units() -> None:
    """No float ever touches a stored monetary value."""
    assert notifications._money(7900, "usd") == "$79.00"
    assert notifications._money(1999, "eur") == "€19.99"
    assert notifications._money(500, "sek") == "5.00 SEK"
    assert notifications._money(None) == "—"


def test_unlimited_limits_read_as_words_not_none() -> None:
    assert notifications._limit_display(None) == "Unlimited"
    assert notifications._limit_display(10_000) == "10,000"


def test_missing_dates_render_as_a_dash() -> None:
    assert notifications._date_display(None) == "—"
    assert (
        notifications._date_display(datetime(2026, 9, 1, tzinfo=timezone.utc))
        == "1 September 2026"
    )
