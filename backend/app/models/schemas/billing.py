"""Subscriptions, plans, usage, invoices and open-source applications."""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from ..enums import (
    InvoiceStatus,
    OssApplicationStatus,
    SubscriptionStatus,
    UsageEngine,
    UsageMeter,
    UserTier,
)


class BillingSubscriptionPublic(SQLModel):
    """The billing page's headline: plan, payment state, and usage.

    ``tier`` is the purchased plan and ``effective_tier`` is what limits are
    actually being applied — they differ exactly when a subscription is
    ``unpaid`` or ``canceled``, and showing both is what lets the UI say "Pro,
    currently limited to Free" instead of silently misreporting one or other.
    """

    id: uuid.UUID
    tier: UserTier
    effective_tier: UserTier
    status: SubscriptionStatus
    analyses_used: int
    fixes_used: int
    repos_used: int = 0
    period_start: datetime | None = None
    period_end: datetime | None = None
    # Populated while ``past_due``: when full service stops if nothing is paid.
    grace_expires_at: datetime | None = None
    cancel_at_period_end: bool = False
    trial_end: datetime | None = None
    # False on deployments with no Stripe credentials, so the UI can hide the
    # upgrade and portal buttons instead of offering a 503.
    billing_enabled: bool = False


class PlanLimitsPublic(SQLModel):
    """``None`` means unlimited, at every layer up to the UI."""

    analyses: int | None = None
    fixes: int | None = None
    repos: int | None = None


class PlanPublic(SQLModel):
    tier: UserTier
    name: str
    price_cents: int
    price_display: str
    tagline: str
    limits: PlanLimitsPublic
    auto_fix: bool
    public_repos_only: bool
    is_purchasable: bool
    features: list[str] = []


class QuotaPublic(SQLModel):
    """One meter's standing for an organization, and the refusal it would draw.

    ``exhausted_reason`` is the whole point: it is the *exact* sentence
    ``enforce_quota`` puts in its 402, or ``None`` when the next unit would go
    through. A client greys a button out on the string alone, and the tooltip
    it shows is then the error it prevented rather than a paraphrase of it —
    the same discipline ``state_machines/engine_target.REASONS`` keeps for the
    activity refusals.
    """

    meter: str
    limit: int | None = None  # None = unlimited (or exempt)
    used: int = 0
    remaining: int | None = None  # None = unlimited
    resets_at: datetime | None = None
    exhausted_reason: str | None = None


class OrgQuotasPublic(SQLModel):
    """Every meter an organization can be refused on."""

    analyses: QuotaPublic
    fixes: QuotaPublic
    repos: QuotaPublic


class UsageBreakdownPublic(SQLModel):
    """How much of one meter a single engine accounted for this period."""

    meter: UsageMeter
    engine: UsageEngine
    quantity: int


class UsagePublic(SQLModel):
    """Per-meter usage with the engine split behind it.

    The breakdown is what answers "why am I at 90%" — before the ledger there
    was no way to tell a user that their Terraform roots, not their workflows,
    were spending the allowance.
    """

    period_start: datetime | None = None
    period_end: datetime | None = None
    analyses_used: int = 0
    fixes_used: int = 0
    repos_used: int = 0
    limits: PlanLimitsPublic
    breakdown: list[UsageBreakdownPublic] = []


class InvoicePublic(SQLModel):
    id: uuid.UUID
    stripe_invoice_id: str
    number: str | None = None
    status: InvoiceStatus
    amount_due_cents: int
    amount_paid_cents: int
    currency: str
    hosted_invoice_url: str | None = None
    invoice_pdf: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    paid_at: datetime | None = None
    created_at: datetime | None = None


class CheckoutRequest(SQLModel):
    tier: UserTier


class CheckoutSessionPublic(SQLModel):
    """The Stripe-hosted URL the browser must be sent to.

    Every way of buying or changing a plan answers with one of these. Both are
    a page on Stripe: a new subscription is a Checkout session, and a change to
    a live one is the Customer Portal's confirmation flow. The client's job is
    the same in either case — navigate — and nothing here reports a new plan,
    because until the customer confirms on Stripe there is not one.
    """

    url: str


class OssApplicationCreate(SQLModel):
    repo_url: str = Field(min_length=1, max_length=512)
    license_name: str = Field(min_length=1, max_length=128)
    justification: str = Field(min_length=1, max_length=4096)


class OssApplicationReview(SQLModel):
    approve: bool
    review_note: str | None = Field(default=None, max_length=2048)


class OssApplicationPublic(SQLModel):
    id: uuid.UUID
    user_id: uuid.UUID
    repo_url: str
    license_name: str
    justification: str
    status: OssApplicationStatus
    review_note: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime | None = None
