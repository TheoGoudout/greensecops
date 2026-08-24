"""The plan catalog — every price, limit and feature flag, declared once.

This module is the **single source of truth** for what each tier is allowed to
do. Nothing else in the codebase may hard-code a limit: the quota enforcer, the
``/billing/plans`` endpoint, the frontend's plan cards and the marketing
pricing table on ``landing/pricing.html`` all derive from ``PLANS`` here.

That last one is enforced mechanically. ``scripts/render_landing_pricing.py``
regenerates the marked regions of the pricing page from this catalog and runs
with ``--check`` in CI, so a limit changed here without regenerating the
landing page fails the build. Before that script existed the two had silently
drifted apart on *every single plan*.

## Reading the limits

``None`` means unlimited. The three meters are:

``analyses``
    One unit per unit of analysis work dispatched, across **every** engine —
    a CI workflow file graded, a Terraform root scanned, a Docker target
    scanned, a cloud account scanned, a telemetry run enriched. They share one
    pool because they are one product; see ``services/billing/usage.py`` for
    exactly when a unit is charged (and when it is not).

``fixes``
    One unit per AI fix *generation*. This is the LLM call, so it is the real
    cost driver and sits at roughly a tenth of the analyses allowance at every
    tier. Regenerating bills again — usage counts generation events, not
    surviving rows.

``repos``
    A capacity limit, not a period one: the number of repositories enabled at
    any one time. Disabling a repo frees the slot back up immediately.

## Why these numbers

The analyses meter spans five engines, so a single push to a repository with
two workflow files, a Terraform root and a Dockerfile costs four analyses, not
one. The limits are scaled for that: 100/month is roughly a month of honest
use on one to three repositories. Starter is 10x Free, and Pro is 10x Starter
for 4.2x the price — the value ladder bends at Pro deliberately. Ultimate earns
its price by removing the ceiling rather than by quoting a bigger number.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import UserTier


@dataclass(frozen=True)
class PlanLimits:
    """Per-meter caps for a tier. ``None`` is unlimited."""

    analyses: int | None
    fixes: int | None
    repos: int | None

    def get(self, meter: str) -> int | None:
        """Look a limit up by meter name, as the quota enforcer does."""
        try:
            return {
                "analyses": self.analyses,
                "fixes": self.fixes,
                "repos": self.repos,
            }[meter]
        except KeyError:
            raise ValueError(f"Unknown meter: {meter!r}") from None


@dataclass(frozen=True)
class Plan:
    """One purchasable (or granted) tier."""

    tier: UserTier
    name: str
    # Monthly price in cents. 0 for free and open_source.
    price_cents: int
    tagline: str
    limits: PlanLimits
    # May enable auto-fix, i.e. automatic PR delivery. A paid feature — see
    # ``services/billing/quota.enforce_auto_fix_enable``.
    auto_fix: bool
    # open_source only: the grant covers public repositories.
    public_repos_only: bool = False
    # Name of the ``settings`` attribute holding this plan's Stripe price id.
    # ``None`` for plans that are never bought through Checkout (free is the
    # default; open_source is granted by review — see OssApplication).
    stripe_price_setting: str | None = None
    # Shown on the pricing page beneath the metered limits. Marketing copy for
    # capabilities that aren't numbers; kept here so the landing page and the
    # in-app plan cards cannot disagree about them either.
    features: tuple[str, ...] = ()

    @property
    def price_display(self) -> str:
        """``$19/mo``-style label used by both the app and the landing page."""
        if self.price_cents == 0:
            return "Free" if self.tier != UserTier.free else "$0/mo"
        return f"${self.price_cents // 100}/mo"

    @property
    def is_purchasable(self) -> bool:
        """Whether Checkout can sell this plan directly."""
        return self.stripe_price_setting is not None


PLANS: dict[UserTier, Plan] = {
    UserTier.free: Plan(
        tier=UserTier.free,
        name="Free",
        price_cents=0,
        tagline="Personal projects and evaluation. No credit card required.",
        limits=PlanLimits(analyses=100, fixes=10, repos=3),
        auto_fix=False,
        features=(
            "Full five-pillar grading",
            "Issue breakdown & detail",
            "Dashboard & history",
        ),
    ),
    UserTier.starter: Plan(
        tier=UserTier.starter,
        name="Starter",
        price_cents=1900,
        tagline="Small teams and growing solo developers.",
        limits=PlanLimits(analyses=1_000, fixes=100, repos=20),
        auto_fix=True,
        stripe_price_setting="STRIPE_PRICE_STARTER",
        features=(
            "Automatic fix pull requests",
            "Pull request status checks",
            "Email notifications",
        ),
    ),
    UserTier.pro: Plan(
        tier=UserTier.pro,
        name="Pro",
        price_cents=7900,
        tagline="Growing teams that need higher limits and faster support.",
        limits=PlanLimits(analyses=10_000, fixes=1_000, repos=100),
        auto_fix=True,
        stripe_price_setting="STRIPE_PRICE_PRO",
        features=(
            "Automatic fix pull requests",
            "Terraform, Docker & cloud scanning",
            "Priority email support",
        ),
    ),
    UserTier.ultimate: Plan(
        tier=UserTier.ultimate,
        name="Ultimate",
        price_cents=29900,
        tagline="Large organisations with unlimited need.",
        limits=PlanLimits(analyses=None, fixes=None, repos=None),
        auto_fix=True,
        stripe_price_setting="STRIPE_PRICE_ULTIMATE",
        features=(
            "Unlimited everything",
            "Dedicated support channel",
            "Custom integrations on request",
        ),
    ),
    UserTier.open_source: Plan(
        tier=UserTier.open_source,
        name="Open Source",
        price_cents=0,
        tagline="For qualifying public open-source projects. Apply with your "
        "repository link.",
        limits=PlanLimits(analyses=2_000, fixes=300, repos=None),
        auto_fix=True,
        public_repos_only=True,
        features=(
            "Automatic fix pull requests",
            "OSS badge for your README",
            "Community support",
        ),
    ),
}

# Display order for pricing cards and comparison tables, cheapest first with
# the granted open-source plan last. Dict order already matches, but stating it
# explicitly keeps presentation from depending on declaration order.
PLAN_ORDER: tuple[UserTier, ...] = (
    UserTier.free,
    UserTier.starter,
    UserTier.pro,
    UserTier.ultimate,
    UserTier.open_source,
)

# The tier every account falls back to: new signups, cancelled subscriptions,
# and paid subscriptions whose grace period ran out.
DEFAULT_TIER = UserTier.free


def get_plan(tier: UserTier | None) -> Plan:
    """Return ``tier``'s plan, falling back to Free for anything unknown.

    Unknown tiers should be impossible (the column is an enum), but a
    fall-through to the *least* privileged plan is the safe direction to fail
    for something that gates spending.
    """
    if tier is None:
        return PLANS[DEFAULT_TIER]
    return PLANS.get(tier, PLANS[DEFAULT_TIER])


def limits_for(tier: UserTier | None) -> PlanLimits:
    """Shorthand for ``get_plan(tier).limits``."""
    return get_plan(tier).limits


def ordered_plans() -> list[Plan]:
    """The catalog in presentation order."""
    return [PLANS[tier] for tier in PLAN_ORDER]


def next_tier_above(tier: UserTier, meter: str) -> Plan | None:
    """The cheapest purchasable plan that raises ``meter`` above ``tier``'s cap.

    Drives the "Upgrade to X for N analyses/month" half of a quota error, so
    the message names a plan that actually solves the user's problem rather
    than pointing vaguely at the pricing page.
    """
    current = limits_for(tier).get(meter)
    if current is None:
        return None
    for plan in ordered_plans():
        if not plan.is_purchasable:
            continue
        candidate = plan.limits.get(meter)
        if candidate is None or candidate > current:
            return plan
    return None
