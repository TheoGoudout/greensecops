"""The usage ledger: what is charged, what is not, and to whom."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from app.core.plans import PLAN_ORDER, PLANS, ordered_plans
from app.models import UsageEngine, UsageMeter, UserTier
from app.services.billing import usage
from tests.utils.billing import (
    link_owner,
    make_org,
    make_repo,
    make_user,
    owned_setup,
    record_usage,
)

# A window around the present rather than a fixed calendar month.
#
# Most tests here stamp their own ``occurred_at`` and would not care, but
# ``test_usage_from_someone_elses_org_is_not_counted`` records through
# ``usage.record_for_repo``, which stamps the wall clock. Against a hard-coded
# August 2026 window that test passed only while August 2026 lasted, and began
# failing on every branch the moment the month turned over.
#
# Anchoring to ``now`` keeps what each constant means — NOW sits inside the
# window, ``PERIOD_START - 1 day`` sits before it, ``PERIOD_END`` is the
# exclusive upper bound — without tying any of it to a date on the calendar.
NOW = datetime.now(timezone.utc)
PERIOD_START = NOW - timedelta(days=14)
PERIOD_END = NOW + timedelta(days=14)


# ─── The catalog is the single source of truth ───────────────────────────────


def test_plan_catalog_matches_the_published_table() -> None:
    """Pin the numbers.

    ``scripts/render_landing_pricing.py --check`` already stops the marketing
    page drifting from this catalog. This stops the catalog itself changing
    without somebody noticing — the two together are why the site and the
    enforcer cannot disagree again.
    """
    expected = {
        UserTier.free: (100, 10, 3),
        UserTier.starter: (1_000, 100, 20),
        UserTier.pro: (10_000, 1_000, 100),
        UserTier.ultimate: (None, None, None),
        UserTier.open_source: (2_000, 300, None),
    }
    actual = {
        tier: (plan.limits.analyses, plan.limits.fixes, plan.limits.repos)
        for tier, plan in PLANS.items()
    }
    assert actual == expected


def test_every_tier_has_a_plan() -> None:
    """A tier with no plan would silently fall back to Free limits."""
    assert set(PLANS) == set(UserTier)
    assert set(PLAN_ORDER) == set(UserTier)
    assert len(ordered_plans()) == len(UserTier)


def test_only_paid_tiers_are_purchasable() -> None:
    purchasable = {p.tier for p in ordered_plans() if p.is_purchasable}
    assert purchasable == {UserTier.starter, UserTier.pro, UserTier.ultimate}


def test_free_tier_cannot_enable_auto_fix() -> None:
    """Auto-fix delivery is the paid feature; everything else is metered."""
    assert PLANS[UserTier.free].auto_fix is False
    for tier in (
        UserTier.starter,
        UserTier.pro,
        UserTier.ultimate,
        UserTier.open_source,
    ):
        assert PLANS[tier].auto_fix is True


# ─── Reading the ledger ──────────────────────────────────────────────────────


def test_period_usage_sums_only_within_the_window(db: Session) -> None:
    user, org, repo = owned_setup(db)
    record_usage(db, user, org, occurred_at=PERIOD_START + timedelta(days=1))
    record_usage(db, user, org, occurred_at=PERIOD_START + timedelta(days=2))
    # Last month: outside [period_start, period_end).
    record_usage(db, user, org, occurred_at=PERIOD_START - timedelta(days=1))
    # Next month: the boundary is exclusive at the top.
    record_usage(db, user, org, occurred_at=PERIOD_END)

    total = usage.period_usage(
        db, user.id, UsageMeter.analyses, PERIOD_START, PERIOD_END
    )
    assert total == 2


def test_period_usage_separates_meters(db: Session) -> None:
    user, org, _repo = owned_setup(db)
    record_usage(db, user, org, meter=UsageMeter.analyses, occurred_at=NOW)
    record_usage(db, user, org, meter=UsageMeter.fixes, occurred_at=NOW)
    record_usage(db, user, org, meter=UsageMeter.fixes, occurred_at=NOW)

    assert (
        usage.period_usage(db, user.id, UsageMeter.analyses, PERIOD_START, PERIOD_END)
        == 1
    )
    assert (
        usage.period_usage(db, user.id, UsageMeter.fixes, PERIOD_START, PERIOD_END) == 2
    )


def test_period_usage_respects_quantity(db: Session) -> None:
    """Records carry a quantity, so the migration's carry-over row counts fully."""
    user, org, _repo = owned_setup(db)
    record_usage(db, user, org, quantity=7, occurred_at=NOW)
    assert (
        usage.period_usage(db, user.id, UsageMeter.analyses, PERIOD_START, PERIOD_END)
        == 7
    )


def test_period_usage_is_scoped_to_one_user(db: Session) -> None:
    user_a, org_a, _ = owned_setup(db)
    user_b, org_b, _ = owned_setup(db)
    record_usage(db, user_a, org_a, occurred_at=NOW)
    record_usage(db, user_b, org_b, occurred_at=NOW)
    record_usage(db, user_b, org_b, occurred_at=NOW)

    assert (
        usage.period_usage(db, user_a.id, UsageMeter.analyses, PERIOD_START, PERIOD_END)
        == 1
    )


def test_breakdown_splits_by_engine(db: Session) -> None:
    """The answer to "why am I at 90%"."""
    user, org, repo = owned_setup(db)
    for engine, count in (
        (UsageEngine.workflow, 3),
        (UsageEngine.terraform, 5),
        (UsageEngine.docker, 1),
    ):
        for _ in range(count):
            record_usage(db, user, org, engine=engine, occurred_at=NOW, repo=repo)

    rows = usage.period_breakdown(db, user.id, PERIOD_START, PERIOD_END)
    as_dict = {(m, e): q for m, e, q in rows}
    assert as_dict[(UsageMeter.analyses, UsageEngine.terraform)] == 5
    assert as_dict[(UsageMeter.analyses, UsageEngine.workflow)] == 3
    assert as_dict[(UsageMeter.analyses, UsageEngine.docker)] == 1
    # Ordered biggest-spender first, which is the order the UI shows.
    assert rows[0][1] == UsageEngine.terraform


# ─── Writing to the ledger ───────────────────────────────────────────────────


def test_record_for_repo_charges_the_billing_owner(db: Session) -> None:
    """Not the acting user — the org's owner, whoever triggered the work."""
    owner, org, repo = owned_setup(db)
    record = usage.record_for_repo(
        db,
        repo=repo,
        meter=UsageMeter.analyses,
        engine=UsageEngine.workflow,
        source_type="analysis",
    )
    assert record is not None
    assert record.user_id == owner.id
    assert record.org_id == org.id
    assert record.repo_id == repo.id


def test_record_for_org_with_no_owner_charges_nobody(db: Session) -> None:
    """An unattributable org is neither billed nor blocked.

    ``quota.enforce_quota`` no-ops in exactly the same case, and the pair has
    to agree: charging without enforcing (or the reverse) would either bill a
    user who cannot be identified or block work nobody can pay for.
    """
    org = make_org(db)  # deliberately no owner member
    repo = make_repo(db, org)
    assert (
        usage.record_for_repo(
            db,
            repo=repo,
            meter=UsageMeter.analyses,
            engine=UsageEngine.workflow,
            source_type="analysis",
        )
        is None
    )


def test_record_attributes_to_the_earliest_joined_owner(db: Session) -> None:
    """A shared org with two owners resolves stably to the first one."""
    org = make_org(db)
    first = make_user(db)
    second = make_user(db)
    link_owner(db, org, first, joined_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    link_owner(db, org, second, joined_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    repo = make_repo(db, org)

    record = usage.record_for_repo(
        db,
        repo=repo,
        meter=UsageMeter.analyses,
        engine=UsageEngine.workflow,
        source_type="analysis",
    )
    assert record is not None
    assert record.user_id == first.id


def test_enabled_repo_ids_tracks_live_capacity(db: Session) -> None:
    """``repos`` is capacity, not consumption: disabling one frees the slot."""
    user, org, repo = owned_setup(db)
    extra = make_repo(db, org)
    assert set(usage.enabled_repo_ids(db, user.id)) == {repo.id, extra.id}

    extra.enabled = False
    db.add(extra)
    db.commit()
    assert set(usage.enabled_repo_ids(db, user.id)) == {repo.id}


def test_usage_from_someone_elses_org_is_not_counted(db: Session) -> None:
    """Riding along as a member of another org must not pool usage."""
    owner, org, repo = owned_setup(db)
    bystander = make_user(db)
    link_owner(db, org, bystander, joined_at=datetime(2030, 1, 1, tzinfo=timezone.utc))

    usage.record_for_repo(
        db,
        repo=repo,
        meter=UsageMeter.analyses,
        engine=UsageEngine.workflow,
        source_type="analysis",
    )
    assert (
        usage.period_usage(db, owner.id, UsageMeter.analyses, PERIOD_START, PERIOD_END)
        >= 1
    )
    assert (
        usage.period_usage(
            db, bystander.id, UsageMeter.analyses, PERIOD_START, PERIOD_END
        )
        == 0
    )
    assert usage.enabled_repo_ids(db, bystander.id) == []
