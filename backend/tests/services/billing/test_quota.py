"""Quota enforcement: who is blocked, who is exempt, and by how much."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app.core import plans
from app.core.plans import Plan, PlanLimits
from app.models import SubscriptionStatus, UsageEngine, UsageMeter, UserTier
from app.services.billing import quota
from app.services.billing.lifecycle import get_or_create_subscription
from tests.utils.billing import (
    link_owner,
    make_org,
    make_repo,
    make_user,
    owned_setup,
    record_usage,
)


def _plan_with(tier: UserTier, **limits: int | None) -> Plan:
    """A copy of ``tier``'s plan with some limits overridden."""
    base = plans.PLANS[tier]
    merged = {
        "analyses": base.limits.analyses,
        "fixes": base.limits.fixes,
        "repos": base.limits.repos,
        **limits,
    }
    return Plan(
        tier=base.tier,
        name=base.name,
        price_cents=base.price_cents,
        tagline=base.tagline,
        limits=PlanLimits(**merged),  # type: ignore[arg-type]
        auto_fix=base.auto_fix,
        public_repos_only=base.public_repos_only,
        stripe_price_setting=base.stripe_price_setting,
        features=base.features,
    )


@pytest.fixture
def tiny_free(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Free tier with a 2-analysis, 1-fix, 1-repo allowance.

    Patching the catalog beats generating a hundred ledger rows per test, and
    it exercises the same code path — the enforcer reads the plan, it does not
    know the numbers.
    """
    patched = dict(plans.PLANS)
    patched[UserTier.free] = _plan_with(UserTier.free, analyses=2, fixes=1, repos=1)
    monkeypatch.setattr(plans, "PLANS", patched)
    return patched


# ─── Exemptions ──────────────────────────────────────────────────────────────


def test_superuser_actor_is_exempt(db: Session, tiny_free: dict) -> None:
    """The platform admin override."""
    _owner, org, _repo = owned_setup(db)
    admin = make_user(db, is_superuser=True)
    quota.enforce_quota(db, admin, org.id, "analyses", requested=1000)  # must not raise


def test_superuser_billing_owner_is_exempt(db: Session, tiny_free: dict) -> None:
    """How a sponsored open-source repo runs without upgrading anyone's tier."""
    owner = make_user(db, is_superuser=True)
    org = make_org(db)
    link_owner(db, org, owner)
    make_repo(db, org)
    actor = make_user(db)
    quota.enforce_quota(db, actor, org.id, "analyses", requested=1000)


def test_org_with_no_billing_owner_is_not_blocked(db: Session, tiny_free: dict) -> None:
    """Nobody to charge means nobody to block.

    ``usage.record_for_org`` declines to charge in the same case; the two have
    to agree or an org would be blocked for spend it never accrued.
    """
    org = make_org(db)
    actor = make_user(db)
    quota.enforce_quota(db, actor, org.id, "analyses", requested=1000)


# ─── Blocking ────────────────────────────────────────────────────────────────


def test_blocks_once_the_allowance_is_spent(db: Session, tiny_free: dict) -> None:
    user, org, _repo = owned_setup(db)
    for _ in range(2):
        record_usage(db, user, org, meter=UsageMeter.analyses)

    with pytest.raises(HTTPException) as exc:
        quota.enforce_quota(db, user, org.id, "analyses")
    assert exc.value.status_code == 402
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "quota_exceeded"
    assert detail["meter"] == "analyses"
    assert detail["limit"] == 2
    assert detail["used"] == 2
    assert detail["remaining"] == 0


def test_batch_request_larger_than_remaining_is_blocked(
    db: Session, tiny_free: dict
) -> None:
    """The bug that let a 20-file analysis through a 1-unit check."""
    user, org, _repo = owned_setup(db)
    record_usage(db, user, org, meter=UsageMeter.analyses)  # 1 of 2 used

    # One more is fine…
    quota.enforce_quota(db, user, org.id, "analyses", requested=1)
    # …but a batch of five is not, even though there is *some* headroom.
    with pytest.raises(HTTPException) as exc:
        quota.enforce_quota(db, user, org.id, "analyses", requested=5)
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail["requested"] == 5
    assert detail["remaining"] == 1
    # The message distinguishes "nothing left" from "not enough left".
    assert "only 1" in detail["message"]


def test_message_names_the_plan_that_solves_it(db: Session) -> None:
    """An upgrade hint pointing at a plan with the same limit would be useless."""
    user, org, _repo = owned_setup(db)
    for _ in range(plans.PLANS[UserTier.free].limits.analyses or 0):
        record_usage(db, user, org, meter=UsageMeter.analyses)

    with pytest.raises(HTTPException) as exc:
        quota.enforce_quota(db, user, org.id, "analyses")
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert "Starter" in detail["message"]
    assert "1,000 analyses/month" in detail["message"]
    assert detail["upgrade_url"].endswith("/billing")


def test_unlimited_tier_never_blocks(db: Session) -> None:
    user, org, _repo = owned_setup(db, tier=UserTier.ultimate)
    get_or_create_subscription(db, user)
    for _ in range(50):
        record_usage(db, user, org, meter=UsageMeter.analyses)
    quota.enforce_quota(db, user, org.id, "analyses", requested=10_000)


def test_debits_the_billing_owner_not_the_acting_teammate(
    db: Session, tiny_free: dict
) -> None:
    """A teammate acting on a shared org must not bypass the owner's cap."""
    owner, org, _repo = owned_setup(db)
    for _ in range(2):
        record_usage(db, owner, org, meter=UsageMeter.analyses)

    teammate = make_user(db)  # own quota untouched
    with pytest.raises(HTTPException):
        quota.enforce_quota(db, teammate, org.id, "analyses")


def test_repos_meter_counts_live_capacity(db: Session, tiny_free: dict) -> None:
    user, org, _repo = owned_setup(db)  # one enabled repo, limit of one
    with pytest.raises(HTTPException) as exc:
        quota.enforce_quota(db, user, org.id, "repos")
    detail = exc.value.detail
    assert isinstance(detail, dict)
    # A repo slot frees up on disable, not at a period boundary, so promising a
    # reset date would be a lie.
    assert detail["resets_at"] is None
    assert "Disable one" in detail["message"]


# ─── The worker-side gate ────────────────────────────────────────────────────


def test_remaining_counts_down(db: Session, tiny_free: dict) -> None:
    user, org, _repo = owned_setup(db)
    assert quota.remaining(db, None, org.id, "analyses") == 2
    record_usage(db, user, org, meter=UsageMeter.analyses)
    assert quota.remaining(db, None, org.id, "analyses") == 1


def test_remaining_is_none_when_unlimited(db: Session) -> None:
    _user, org, _repo = owned_setup(db, tier=UserTier.ultimate)
    assert quota.remaining(db, None, org.id, "analyses") is None


def test_exhausted_message_only_when_spent(db: Session, tiny_free: dict) -> None:
    """What a Celery task uses — it has nobody to raise a 402 at."""
    user, org, _repo = owned_setup(db)
    assert quota.exhausted_message(db, org.id) is None

    for _ in range(2):
        record_usage(db, user, org, meter=UsageMeter.analyses)
    message = quota.exhausted_message(db, org.id, engine=UsageEngine.terraform)
    assert message is not None
    # Same builder as the API error, so both surfaces quote the same numbers.
    assert "Free plan" in message
    assert "Upgrade to Starter" in message


# ─── Entitlement feeds enforcement ───────────────────────────────────────────


def test_unpaid_subscription_is_metered_at_free_limits(db: Session) -> None:
    """Grace expiry has teeth: a Pro account past its window gets Free caps."""
    user, org, _repo = owned_setup(db, tier=UserTier.pro)
    sub = get_or_create_subscription(db, user)
    sub.status = SubscriptionStatus.unpaid
    db.add(sub)
    db.commit()

    state = quota.state_for_org(db, None, org.id, "analyses")
    assert state.tier == UserTier.free
    assert state.limit == plans.PLANS[UserTier.free].limits.analyses


def test_past_due_subscription_keeps_paid_limits(db: Session) -> None:
    """The whole point of the grace window: nothing changes while it is open."""
    user, org, _repo = owned_setup(db, tier=UserTier.pro)
    sub = get_or_create_subscription(db, user)
    sub.status = SubscriptionStatus.past_due
    db.add(sub)
    db.commit()

    state = quota.state_for_org(db, None, org.id, "analyses")
    assert state.tier == UserTier.pro
    assert state.limit == plans.PLANS[UserTier.pro].limits.analyses


# ─── Auto-fix gate ───────────────────────────────────────────────────────────


def test_auto_fix_refused_on_free(db: Session) -> None:
    user, org, _repo = owned_setup(db)
    with pytest.raises(HTTPException) as exc:
        quota.enforce_auto_fix_enable(db, user, org.id)
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "feature_not_in_plan"
    assert "Starter" in detail["message"]


def test_auto_fix_allowed_on_a_paid_plan(db: Session) -> None:
    user, org, _repo = owned_setup(db, tier=UserTier.starter)
    get_or_create_subscription(db, user)
    quota.enforce_auto_fix_enable(db, user, org.id)  # must not raise


def test_auto_fix_refused_once_grace_expires(db: Session) -> None:
    """An unpaid Pro account must not keep opening fix PRs."""
    user, org, _repo = owned_setup(db, tier=UserTier.pro)
    sub = get_or_create_subscription(db, user)
    sub.status = SubscriptionStatus.unpaid
    db.add(sub)
    db.commit()

    with pytest.raises(HTTPException):
        quota.enforce_auto_fix_enable(db, user, org.id)


# ─── Snapshot ────────────────────────────────────────────────────────────────


def test_snapshot_reads_every_meter_against_one_period(db: Session) -> None:
    user, org, repo = owned_setup(db)
    record_usage(db, user, org, meter=UsageMeter.analyses, repo=repo)
    record_usage(db, user, org, meter=UsageMeter.analyses, repo=repo)
    record_usage(db, user, org, meter=UsageMeter.fixes, repo=repo)

    snap = quota.snapshot(db, user)
    assert snap.analyses_used == 2
    assert snap.fixes_used == 1
    assert snap.repos_used == 1
    # The period is rolled before the read, never straddled mid-way.
    assert snap.subscription.period_start is not None
    assert snap.subscription.period_end is not None
    assert snap.subscription.period_start < datetime.now(timezone.utc)
