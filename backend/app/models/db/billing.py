import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Index
from sqlmodel import Field, Relationship, SQLModel

from ..enums import (
    InvoiceStatus,
    OssApplicationStatus,
    SubscriptionStatus,
    UsageEngine,
    UsageMeter,
    UserTier,
)
from .base import get_datetime_utc

if TYPE_CHECKING:
    from .user import User


class BillingSubscription(SQLModel, table=True):
    """One account's plan, its payment state, and its current billing period.

    ``tier`` is what was bought; ``status`` is whether it is currently being
    paid for. Neither alone decides what the account may do — quota enforcement
    reads ``services/billing/lifecycle.effective_tier``, which combines them so
    that an ``unpaid`` Pro subscription is metered at Free limits without
    losing the knowledge that it is a Pro subscription waiting to be restored.
    """

    __tablename__ = "billing_subscription"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", unique=True, nullable=False, ondelete="CASCADE"
    )
    tier: UserTier = Field(default=UserTier.free)
    status: SubscriptionStatus = Field(
        default=SubscriptionStatus.active,
        sa_column_kwargs={"server_default": SubscriptionStatus.active.value},
    )
    stripe_subscription_id: str | None = Field(
        default=None, max_length=255, unique=True
    )
    stripe_customer_id: str | None = Field(default=None, max_length=255)
    period_start: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    period_end: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))

    # ─── Dunning / grace ──────────────────────────────────────────────────
    # When the current run of failed payments began. Cleared on recovery, so a
    # subscription that fails, pays, and fails again gets a fresh window rather
    # than inheriting the first failure's remaining days.
    past_due_since: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )
    # ``past_due_since + BILLING_GRACE_PERIOD_DAYS``, stored rather than derived
    # so an operator can extend one account's window without a code change.
    grace_expires_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )
    # Index of the last dunning reminder sent (0 = none). Persisted so a beat
    # re-run, a worker restart, or a redelivered Stripe webhook cannot send the
    # same reminder twice.
    dunning_stage: int = Field(default=0)
    # Highest usage percentage a warning has already been sent for this period
    # (0 = none). Reset by the period rollover, so each month gets its own
    # 80%/100% warnings rather than one warning ever.
    quota_warning_percent: int = Field(default=0)
    trial_end: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    # Set when the user cancels from the Stripe portal: service continues to
    # ``period_end``, then ``period_ended`` moves the row to ``canceled``.
    cancel_at_period_end: bool = Field(default=False)
    canceled_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))

    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    user: Optional["User"] = Relationship(back_populates="billing_subscription")
    invoices: list["Invoice"] = Relationship(
        back_populates="subscription", cascade_delete=True
    )


class BillingUsageRecord(SQLModel, table=True):
    """One unit of metered work, appended when the work is created.

    An append-only ledger rather than a set of counters. Counters cannot say
    *what* consumed an allowance, cannot be recomputed after a bug, and — as
    the previous ``fixes_used_baseline`` snapshot showed — do not survive the
    product growing from one analysis engine to five.

    Period usage is ``SUM(quantity)`` over ``[period_start, period_end)``,
    served by the composite index below. See ``services/billing/usage.py`` for
    the rules about exactly when a record is written.
    """

    __tablename__ = "billing_usage_record"
    __table_args__ = (
        # The only shape ever queried: one user's spend on one meter within a
        # period. ``occurred_at`` last so the range scan runs on a prefix match.
        Index(
            "ix_billing_usage_record_user_meter_time",
            "user_id",
            "meter",
            "occurred_at",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # The billing owner resolved at the moment the work happened. Denormalised
    # deliberately: re-resolving it later would re-bill history to whoever owns
    # the org today, silently rewriting past periods when ownership changes.
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    org_id: uuid.UUID = Field(
        foreign_key="organization.id", nullable=False, ondelete="CASCADE"
    )
    # NULL for cloud-account scans, which are org-level and belong to no repo.
    repo_id: uuid.UUID | None = Field(
        default=None, foreign_key="repository.id", nullable=True, ondelete="SET NULL"
    )
    meter: UsageMeter = Field(nullable=False)
    engine: UsageEngine = Field(nullable=False)
    quantity: int = Field(default=1)
    # The row that caused the charge — ``"analysis"``, ``"terraform_scan"``,
    # ``"fix"``… Free-form rather than an FK because it spans seven tables; it
    # exists for auditing ("why was I charged"), not for joins.
    source_type: str = Field(max_length=64)
    source_id: uuid.UUID | None = Field(default=None)
    occurred_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )


class Invoice(SQLModel, table=True):
    """A Stripe invoice, mirrored so billing history survives without Stripe.

    Amounts are stored in the currency's minor unit (cents), exactly as Stripe
    reports them — no float ever touches a monetary value.
    """

    __tablename__ = "billing_invoice"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    subscription_id: uuid.UUID = Field(
        foreign_key="billing_subscription.id", nullable=False, ondelete="CASCADE"
    )
    stripe_invoice_id: str = Field(max_length=255, unique=True, index=True)
    status: InvoiceStatus = Field(default=InvoiceStatus.draft)
    amount_due_cents: int = Field(default=0)
    amount_paid_cents: int = Field(default=0)
    currency: str = Field(default="usd", max_length=8)
    number: str | None = Field(default=None, max_length=64)
    # Stripe-hosted payment page and PDF. Kept so a dunning email can link
    # straight to the thing that needs paying.
    hosted_invoice_url: str | None = Field(default=None, max_length=1024)
    invoice_pdf: str | None = Field(default=None, max_length=1024)
    period_start: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    period_end: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    due_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    paid_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    subscription: Optional["BillingSubscription"] = Relationship(
        back_populates="invoices"
    )


class OssApplication(SQLModel, table=True):
    """A request for the granted open-source plan, awaiting review.

    The pricing page has advertised "Apply for OSS plan" since launch with
    nothing behind the button. Approval is a human decision (is this project
    genuinely open source?), so this is a review queue rather than an automatic
    grant.
    """

    __tablename__ = "billing_oss_application"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    repo_url: str = Field(max_length=512)
    license_name: str = Field(max_length=128)
    justification: str = Field(max_length=4096)
    status: OssApplicationStatus = Field(
        default=OssApplicationStatus.pending,
        sa_column_kwargs={"server_default": OssApplicationStatus.pending.value},
    )
    # Free-text note from the reviewer, shown to the applicant on rejection so
    # a decline is actionable rather than silent.
    review_note: str | None = Field(default=None, max_length=2048)
    reviewed_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    reviewed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )


class BillingWebhookEvent(SQLModel, table=True):
    """Stripe event ids already processed, for idempotency.

    Stripe retries on any non-2xx and can redeliver on its own schedule, so
    without this a redelivered ``invoice.payment_failed`` would re-send a
    dunning email and a redelivered ``customer.subscription.updated`` would
    re-run a transition. The row is inserted inside the handler's transaction,
    so a handler that fails and returns 500 leaves no row and is safely retried.
    """

    __tablename__ = "billing_webhook_event"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    stripe_event_id: str = Field(max_length=255, unique=True, index=True)
    event_type: str = Field(max_length=128)
    received_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
