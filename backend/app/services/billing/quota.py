"""Quota enforcement — reading the ledger and deciding what may run.

## Two gates, not one

Enforcement happens at **two** points, and both are necessary:

1. **At the API boundary**, before work is queued. Fast, and it lets the user
   see a precise 402 instead of watching a job vanish into a worker.
2. **In the worker**, immediately before each unit of work is created. This is
   the gate that actually holds.

The second one exists because the first one cannot be trusted on its own. A
single ``POST /workflow/repositories/{repo_id}/scans`` fans out to one analysis *per workflow
file*, so a pre-check for "1" let a user at 49/50 create twenty. Worse, most
analyses are never triggered through the API at all — they come from push
webhooks, from polling external repos, and from installation sync, none of
which had any quota check whatsoever. Putting the real gate in the worker
covers every one of those paths at once, because they all funnel through it.

## What is exempt

* A **superuser caller** — the platform admin override.
* An org whose **billing owner is a superuser** — how a sponsored open-source
  repo runs without upgrading anyone's tier.
* An org with **no resolvable billing owner** — there is nobody to charge, so
  blocking would punish a user for our bookkeeping. ``usage.record_for_org``
  declines to charge in exactly the same case, so such an org is consistently
  neither billed nor blocked.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session

from app.core.plans import get_plan, limits_for
from app.models import (
    BillingSubscription,
    UsageEngine,
    UsageMeter,
    User,
    UserTier,
)

from . import errors, usage
from .lifecycle import (
    effective_tier,
    ensure_current_period,
    get_or_create_subscription,
)
from .owner import org_billing_owner

# Meters that draw from the ledger. ``repos`` is a live capacity count and is
# handled separately — see ``usage.enabled_repo_ids``.
_LEDGER_METERS = {"analyses": UsageMeter.analyses, "fixes": UsageMeter.fixes}


@dataclass(frozen=True)
class QuotaState:
    """Everything needed to allow, refuse, or explain a metered request."""

    # ``None`` when the request is exempt from enforcement entirely.
    tier: UserTier | None
    limit: int | None  # None = unlimited
    used: int
    resets_at: datetime | None
    exempt: bool = False

    @property
    def unlimited(self) -> bool:
        return self.exempt or self.limit is None

    @property
    def remaining(self) -> int | None:
        """Units left, or ``None`` for unlimited."""
        if self.unlimited:
            return None
        assert self.limit is not None
        return max(self.limit - self.used, 0)

    def allows(self, requested: int) -> bool:
        remaining = self.remaining
        return remaining is None or requested <= remaining


def usage_for(
    session: Session, user: User, meter: str
) -> tuple[int, BillingSubscription]:
    """Current-period usage of ``meter`` for ``user``, rolling the period first.

    Rollover happens before the read, in that order, always — reading a stale
    period would report last month's spend against this month's limit.
    """
    sub = ensure_current_period(session, get_or_create_subscription(session, user))
    if meter == "repos":
        return len(usage.enabled_repo_ids(session, user.id)), sub
    return (
        usage.period_usage(
            session, user.id, _LEDGER_METERS[meter], sub.period_start, sub.period_end
        ),
        sub,
    )


@dataclass(frozen=True)
class UsageSnapshot:
    """All three meters for one account, read against one billing period."""

    analyses_used: int
    fixes_used: int
    repos_used: int
    subscription: BillingSubscription


def snapshot(session: Session, user: User) -> UsageSnapshot:
    """Read every meter once, against a single freshly-rolled period.

    Calling ``usage_for`` three times would re-fetch and re-roll the
    subscription each time, and — worse — could straddle a period boundary
    mid-read, reporting two meters against different months.
    """
    sub = ensure_current_period(session, get_or_create_subscription(session, user))
    return UsageSnapshot(
        analyses_used=usage.period_usage(
            session, user.id, UsageMeter.analyses, sub.period_start, sub.period_end
        ),
        fixes_used=usage.period_usage(
            session, user.id, UsageMeter.fixes, sub.period_start, sub.period_end
        ),
        repos_used=len(usage.enabled_repo_ids(session, user.id)),
        subscription=sub,
    )


def state_for_org(
    session: Session,
    actor: User | None,
    org_id: uuid.UUID,
    meter: str,
) -> QuotaState:
    """Resolve ``org_id``'s billing owner and read their standing on ``meter``.

    ``actor`` is the user who triggered the work, or ``None`` for work with no
    human behind it (a push webhook, the polling sweep). A ``None`` actor is
    never exempt on its own — the org's billing owner still decides.
    """
    if actor is not None and actor.is_superuser:
        return QuotaState(tier=None, limit=None, used=0, resets_at=None, exempt=True)
    owner = org_billing_owner(session, org_id)
    if owner is None or owner.is_superuser:
        return QuotaState(tier=None, limit=None, used=0, resets_at=None, exempt=True)

    used, sub = usage_for(session, owner, meter)
    tier = effective_tier(sub)
    return QuotaState(
        tier=tier,
        limit=limits_for(tier).get(meter),
        used=used,
        resets_at=sub.period_end,
    )


# Every meter a caller can be refused on, in the order the UI reads them.
METERS: tuple[str, ...] = ("analyses", "fixes", "repos")


def states_for_org(
    session: Session,
    actor: User | None,
    org_id: uuid.UUID,
) -> dict[str, QuotaState]:
    """Every meter's standing for ``org_id``, read against one billing period.

    ``state_for_org`` three times would roll the owner's subscription three
    times and could straddle a period boundary mid-read — the same hazard
    ``snapshot`` exists to avoid, one level up. This is the read behind
    ``GET /billing/organizations/{org_id}/quotas``, which is what lets the UI
    grey out "Scan now" *before* the click instead of after the 402.

    Resolving through the org's billing owner rather than ``actor`` is the whole
    point: it is who ``enforce_quota`` measures, so a teammate on a shared org
    is shown the numbers they will actually be blocked by.
    """
    exempt = QuotaState(tier=None, limit=None, used=0, resets_at=None, exempt=True)
    if actor is not None and actor.is_superuser:
        return dict.fromkeys(METERS, exempt)
    owner = org_billing_owner(session, org_id)
    if owner is None or owner.is_superuser:
        return dict.fromkeys(METERS, exempt)

    snap = snapshot(session, owner)
    tier = effective_tier(snap.subscription)
    limits = limits_for(tier)
    used = {
        "analyses": snap.analyses_used,
        "fixes": snap.fixes_used,
        "repos": snap.repos_used,
    }
    return {
        meter: QuotaState(
            tier=tier,
            limit=limits.get(meter),
            used=used[meter],
            # A repo slot is capacity, not consumption — it frees when a repo is
            # disabled, not at a period boundary. ``errors.quota_exceeded``
            # drops the reset date for the same reason.
            resets_at=None if meter == "repos" else snap.subscription.period_end,
        )
        for meter in METERS
    }


def refusal_for(
    state: QuotaState,
    meter: str,
    requested: int = 1,
    *,
    engine: UsageEngine | None = None,
) -> str | None:
    """The sentence ``enforce_quota`` would raise for ``state``, or ``None``.

    Built from the same ``errors.quota_exceeded`` the 402 comes from, so a
    tooltip that greys a button out and the error it prevents are the same
    words — the discipline ``engine_target.REASONS`` already keeps for activity.
    """
    if state.allows(requested):
        return None
    assert state.tier is not None and state.limit is not None
    detail = errors.quota_exceeded(
        meter=meter,
        tier=state.tier,
        limit=state.limit,
        used=state.used,
        requested=requested,
        resets_at=state.resets_at,
        engine=engine.value if engine else None,
    ).detail
    assert isinstance(detail, dict)
    return str(detail["message"])


def remaining(
    session: Session,
    actor: User | None,
    org_id: uuid.UUID,
    meter: str,
) -> int | None:
    """Units of ``meter`` ``org_id`` may still consume; ``None`` for unlimited.

    The worker-side gate: cheap enough to call before each unit of a batch, so
    a twenty-file analysis stops at the cap instead of blowing through it.
    """
    return state_for_org(session, actor, org_id, meter).remaining


def exhausted_message(
    session: Session,
    org_id: uuid.UUID,
    meter: str = "analyses",
    *,
    engine: UsageEngine | None = None,
) -> str | None:
    """The refusal wording if ``meter`` is spent for ``org_id``, else ``None``.

    The worker-side counterpart to ``enforce_quota``: a Celery task has nobody
    to raise a 402 at, so it needs the sentence rather than the exception. Both
    come from the same builder, so a user reading an SSE toast and a user
    reading an API error see the same numbers and the same upgrade advice.
    """
    return refusal_for(
        state_for_org(session, None, org_id, meter), meter, engine=engine
    )


def enforce_quota(
    session: Session,
    current_user: User | None,
    org_id: uuid.UUID,
    kind: str,
    *,
    requested: int = 1,
    engine: UsageEngine | None = None,
) -> None:
    """Raise a structured 402 if ``requested`` more units would exceed the cap.

    ``kind`` is one of ``"analyses"``, ``"fixes"`` or ``"repos"``. Usage for
    every kind is cumulative — it never decreases as items are deleted or
    replaced — so regenerating a fix bills like a new one.

    Measured against the org's billing owner rather than ``current_user``, so a
    non-owner teammate acting on a shared org debits (and is blocked by) the
    real billing owner's quota instead of silently bypassing it.
    """
    state = state_for_org(session, current_user, org_id, kind)
    if state.allows(requested):
        return
    assert state.tier is not None and state.limit is not None
    raise errors.quota_exceeded(
        meter=kind,
        tier=state.tier,
        limit=state.limit,
        used=state.used,
        requested=requested,
        resets_at=state.resets_at,
        engine=engine.value if engine else None,
    )


def enforce_auto_fix_enable(
    session: Session,
    current_user: User,
    org_id: uuid.UUID,
) -> None:
    """Raise 402 unless auto-fix may be enabled for ``org_id``.

    Auto-fix (automatic PR delivery) is a paid feature: only a platform
    superuser or an org whose billing owner is on a plan that includes it may
    turn it on. A superuser caller (or superuser billing owner) is exempt —
    that is the mechanism for force-enabling auto-fix on a sponsored
    open-source repo without upgrading its org's tier.

    Uses the *effective* tier, so an unpaid Pro subscription cannot keep
    opening fix PRs through its grace expiry.
    """
    if current_user.is_superuser:
        return
    owner = org_billing_owner(session, org_id)
    if owner is None or owner.is_superuser:
        return
    sub = get_or_create_subscription(session, owner)
    tier = effective_tier(sub)
    if get_plan(tier).auto_fix:
        return
    raise errors.feature_not_in_plan(
        feature="Automatic fix pull requests",
        tier=tier,
        required_plan_name="Starter",
    )
