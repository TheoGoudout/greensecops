"""Tests for the /api/v1/billing/ endpoints."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.routes import billing
from app.core.config import settings
from app.models import (
    Analysis,
    AnalysisStatus,
    Fix,
    FixStatus,
    LLMProvider,
    Organization,
    OrgMember,
    OrgRole,
    Repository,
    User,
    UserTier,
    WorkflowFile,
)

# ─── Fixtures ─────────────────────────────────────────────────────────────────


def _make_user(
    db: Session, *, tier: UserTier = UserTier.free, is_superuser: bool = False
) -> User:
    user = User(
        email=f"u-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        is_superuser=is_superuser,
        tier=tier,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_org(db: Session) -> Organization:
    org = Organization(name=f"org-{uuid.uuid4().hex[:8]}")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _link_owner(
    db: Session, org: Organization, user: User, *, joined_at: datetime | None = None
) -> OrgMember:
    member = OrgMember(
        org_id=org.id,
        user_id=user.id,
        role=OrgRole.owner,
        joined_at=joined_at or datetime.now(timezone.utc),
    )
    db.add(member)
    db.commit()
    return member


def _make_repo(db: Session, org: Organization, *, enabled: bool = True) -> Repository:
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=99999,
        enabled=enabled,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo


def _make_workflow_file(db: Session, repo: Repository) -> WorkflowFile:
    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/ci.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="name: CI\non: push\njobs: {}\n",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


def _make_completed_analysis(
    db: Session, repo: Repository, wf: WorkflowFile
) -> Analysis:
    analysis = Analysis(
        repo_id=repo.id,
        workflow_file_id=wf.id,
        content_hash=wf.content_hash,
        status=AnalysisStatus.completed,
        # Real completion code always sets this (static_analysis.py); usage
        # is now scoped to the current billing period by this timestamp.
        completed_at=datetime.now(timezone.utc),
    )
    db.add(analysis)
    db.commit()
    return analysis


def _make_fix(db: Session, wf: WorkflowFile) -> Fix:
    fix = Fix(
        workflow_file_id=wf.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o",
        status=FixStatus.ready,
    )
    db.add(fix)
    # fixes_used counts this cumulative counter, not live Fix rows (a
    # regenerate deletes and recreates the row) — mirror what the real
    # generation route does when it creates a Fix.
    wf.fix_generation_count += 1
    db.add(wf)
    db.commit()
    return fix


# ─── enforce_quota ────────────────────────────────────────────────────────────


def test_enforce_quota_superuser_actor_exempt(db: Session) -> None:
    # A superuser *actor* bypasses quota outright, regardless of the target
    # org's billing owner — org_id doesn't even need to resolve to anything.
    actor = User(
        email=f"su-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        is_superuser=True,
        tier=UserTier.free,
    )
    with patch.dict(billing._TIER_LIMITS, {UserTier.free: {"fixes": 0}}):
        billing.enforce_quota(db, actor, uuid.uuid4(), "fixes")  # must not raise


def test_enforce_quota_superuser_actor_bypasses_even_at_owners_limit(
    db: Session,
) -> None:
    # The acting user is a superuser, but the org's real billing owner is a
    # separate, regular user already at their limit. The admin override must
    # still bypass the check.
    actor = User(
        email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        is_superuser=True,
        tier=UserTier.free,
    )
    owner = _make_user(db)
    org = _make_org(db)
    _link_owner(db, org, owner)
    with (
        patch.dict(billing._TIER_LIMITS, {UserTier.free: {"fixes": 0}}),
        patch.object(billing, "_usage_for_user", return_value=(0, 0, [], None)),
    ):
        billing.enforce_quota(db, actor, org.id, "fixes")  # must not raise


def test_enforce_quota_blocks_at_limit(db: Session) -> None:
    user = _make_user(db)
    org = _make_org(db)
    _link_owner(db, org, user)
    with patch.dict(billing._TIER_LIMITS, {UserTier.free: {"fixes": 0}}):
        with pytest.raises(HTTPException) as exc:
            billing.enforce_quota(db, user, org.id, "fixes")
    assert exc.value.status_code == 402


def test_enforce_quota_no_billing_owner_does_not_raise(db: Session) -> None:
    # An org with no resolvable owner (e.g. orphaned data) can't be billed
    # against — enforce_quota no-ops rather than crashing.
    user = _make_user(db)
    with patch.dict(billing._TIER_LIMITS, {UserTier.free: {"fixes": 0}}):
        billing.enforce_quota(db, user, uuid.uuid4(), "fixes")  # must not raise


def test_enforce_quota_regenerate_counts_as_new_usage(db: Session) -> None:
    # Usage is a cumulative generation-event count, not a live-row count, so
    # regenerating existing fixes has no "replacing" offset anymore — it must
    # be blocked exactly like a brand-new generation once at the limit.
    user = _make_user(db)
    org = _make_org(db)
    _link_owner(db, org, user)
    with (
        patch.dict(billing._TIER_LIMITS, {UserTier.free: {"fixes": 5}}),
        patch.object(billing, "_usage_for_user", return_value=(0, 5, [], None)),
        pytest.raises(HTTPException) as exc,
    ):
        billing.enforce_quota(db, user, org.id, "fixes", requested=1)
    assert exc.value.status_code == 402


def test_enforce_quota_default_still_blocks_at_limit(db: Session) -> None:
    user = _make_user(db)
    org = _make_org(db)
    _link_owner(db, org, user)
    with (
        patch.dict(billing._TIER_LIMITS, {UserTier.free: {"fixes": 5}}),
        patch.object(billing, "_usage_for_user", return_value=(0, 5, [], None)),
        pytest.raises(HTTPException) as exc,
    ):
        billing.enforce_quota(db, user, org.id, "fixes")
    assert exc.value.status_code == 402


def test_enforce_quota_unlimited_tier(db: Session) -> None:
    user = _make_user(db, tier=UserTier.ultimate)
    org = _make_org(db)
    _link_owner(db, org, user)
    # ultimate has None (unlimited) for fixes → never blocks.
    billing.enforce_quota(db, user, org.id, "fixes")  # must not raise


def test_enforce_quota_repos_kind_blocks_at_limit(db: Session) -> None:
    user = _make_user(db)
    org = _make_org(db)
    _link_owner(db, org, user)
    with (
        patch.dict(billing._TIER_LIMITS, {UserTier.free: {"repos": 3}}),
        patch.object(
            billing,
            "_usage_for_user",
            return_value=(0, 0, [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()], None),
        ),
        pytest.raises(HTTPException) as exc,
    ):
        billing.enforce_quota(db, user, org.id, "repos")
    assert exc.value.status_code == 402
    assert "Repos quota" in exc.value.detail


# ─── Usage counting: monotonicity + org pooling ──────────────────────────────


def test_disabling_repo_does_not_change_analyses_or_fixes_used(db: Session) -> None:
    user = _make_user(db)
    org = _make_org(db)
    _link_owner(db, org, user)
    repo = _make_repo(db, org, enabled=True)
    wf = _make_workflow_file(db, repo)
    _make_completed_analysis(db, repo, wf)
    _make_fix(db, wf)

    analyses_before, fixes_before, repos_before, _sub = billing._usage_for_user(
        db, user
    )
    assert analyses_before == 1
    assert fixes_before == 1
    assert repos_before == [repo.id]

    repo.enabled = False
    db.add(repo)
    db.commit()

    analyses_after, fixes_after, repos_after, _sub = billing._usage_for_user(db, user)
    assert analyses_after == 1
    assert fixes_after == 1
    assert repos_after == []  # repos_used is a live "currently enabled" count

    repo.enabled = True
    db.add(repo)
    db.commit()

    analyses_final, fixes_final, repos_final, _sub = billing._usage_for_user(db, user)
    assert analyses_final == 1
    assert fixes_final == 1
    assert repos_final == [repo.id]


def test_second_org_owner_does_not_inherit_pooled_usage(db: Session) -> None:
    org = _make_org(db)
    first_owner = _make_user(db)
    second_owner = _make_user(db)
    now = datetime.now(timezone.utc)
    _link_owner(db, org, first_owner, joined_at=now)
    _link_owner(db, org, second_owner, joined_at=now + timedelta(minutes=1))

    repo = _make_repo(db, org)
    wf = _make_workflow_file(db, repo)
    _make_completed_analysis(db, repo, wf)
    _make_fix(db, wf)

    analyses_first, fixes_first, repos_first, _sub = billing._usage_for_user(
        db, first_owner
    )
    assert analyses_first == 1
    assert fixes_first == 1
    assert repos_first == [repo.id]

    analyses_second, fixes_second, repos_second, _sub = billing._usage_for_user(
        db, second_owner
    )
    assert analyses_second == 0
    assert fixes_second == 0
    assert repos_second == []


def test_fixes_used_pools_across_all_orgs_owned_by_user(db: Session) -> None:
    # A user who owns two separate orgs (e.g. two linked GitHub accounts) has
    # their fixes_used pooled across both, not scoped to just one.
    user = _make_user(db)
    org_a = _make_org(db)
    org_b = _make_org(db)
    _link_owner(db, org_a, user)
    _link_owner(db, org_b, user)

    repo_a = _make_repo(db, org_a)
    wf_a = _make_workflow_file(db, repo_a)
    _make_fix(db, wf_a)

    repo_b = _make_repo(db, org_b)
    wf_b = _make_workflow_file(db, repo_b)
    _make_fix(db, wf_b)

    _, fixes_used, _, _sub = billing._usage_for_user(db, user)
    assert fixes_used == 2


def test_fixes_used_survives_fix_row_delete_and_recreate(db: Session) -> None:
    # Regenerating a fix deletes and recreates its Fix row (see
    # _create_pending_fixes) — fixes_used must still grow with each
    # generation event instead of resetting to the live row count.
    user = _make_user(db)
    org = _make_org(db)
    _link_owner(db, org, user)
    repo = _make_repo(db, org)
    wf = _make_workflow_file(db, repo)

    fix = _make_fix(db, wf)
    _, fixes_used, _, _sub = billing._usage_for_user(db, user)
    assert fixes_used == 1

    db.delete(fix)
    db.commit()
    _make_fix(db, wf)  # regenerate: new row, same workflow file

    _, fixes_used, _, _sub = billing._usage_for_user(db, user)
    assert fixes_used == 2


def test_enforce_quota_debits_billing_owner_not_acting_teammate(db: Session) -> None:
    # A non-owner teammate acting on the org's repo is still checked and
    # blocked against the real billing owner's quota.
    org = _make_org(db)
    owner = _make_user(db)
    teammate = _make_user(db)
    _link_owner(db, org, owner)
    with (
        patch.dict(billing._TIER_LIMITS, {UserTier.free: {"fixes": 0}}),
        pytest.raises(HTTPException) as exc,
    ):
        billing.enforce_quota(db, teammate, org.id, "fixes")
    assert exc.value.status_code == 402


# ─── monthly usage reset ─────────────────────────────────────────────────────


def test_month_bounds_mid_month() -> None:
    now = datetime(2026, 7, 20, 15, 30, tzinfo=timezone.utc)
    start, end = billing._month_bounds(now)
    assert start == datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_month_bounds_december_rolls_into_next_year() -> None:
    now = datetime(2026, 12, 25, tzinfo=timezone.utc)
    start, end = billing._month_bounds(now)
    assert start == datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert end == datetime(2027, 1, 1, tzinfo=timezone.utc)


def test_first_ever_period_does_not_baseline_away_existing_usage(db: Session) -> None:
    # A user who already generated fixes before their subscription's first
    # period check must still see that usage counted — there is no prior
    # period to exclude it from.
    user = _make_user(db)
    org = _make_org(db)
    _link_owner(db, org, user)
    repo = _make_repo(db, org)
    wf = _make_workflow_file(db, repo)
    _make_fix(db, wf)

    _, fixes_used, _, sub = billing._usage_for_user(db, user)
    assert fixes_used == 1
    assert sub.fixes_used_baseline == 0
    assert sub.period_start is not None
    assert sub.period_end is not None


def test_rollover_resets_period_usage_but_keeps_lifetime_count(db: Session) -> None:
    # Simulated month crossing (not real elapsed time) — a real calendar
    # rollover can't be forced just by editing period_end while "now" is
    # still in the same month _month_bounds would recompute.
    user = _make_user(db)
    org = _make_org(db)
    _link_owner(db, org, user)
    repo = _make_repo(db, org)
    wf = _make_workflow_file(db, repo)

    with patch.object(
        billing,
        "get_datetime_utc",
        return_value=datetime(2026, 6, 15, tzinfo=timezone.utc),
    ):
        fix = _make_fix(db, wf)
        _, fixes_used, _, sub = billing._usage_for_user(db, user)
    assert fixes_used == 1
    assert sub.period_start == datetime(2026, 6, 1, tzinfo=timezone.utc)

    with patch.object(
        billing,
        "get_datetime_utc",
        return_value=datetime(2026, 7, 5, tzinfo=timezone.utc),
    ):
        # Rollover is checked first — same order enforce_quota always uses in
        # production (quota check precedes fix creation in the same request),
        # so the baseline snapshot never includes usage from the new period.
        _, _, _, rolled_sub = billing._usage_for_user(db, user)
        assert rolled_sub.fixes_used_baseline == 1

        # Regenerate (delete + recreate, same as the real fix-generation
        # flow — Fix.workflow_file_id is unique) one more fix in the new month.
        db.delete(fix)
        db.commit()
        _make_fix(db, wf)
        _, fixes_used_after_rollover, _, sub_after = billing._usage_for_user(db, user)

    # Only the fix generated in the new period counts...
    assert fixes_used_after_rollover == 1
    # ...but the lifetime baseline reflects everything generated before rollover.
    assert sub_after.fixes_used_baseline == 1
    assert sub_after.period_start == datetime(2026, 7, 1, tzinfo=timezone.utc)


def test_analyses_used_excludes_completions_from_before_current_period(
    db: Session,
) -> None:
    user = _make_user(db)
    org = _make_org(db)
    _link_owner(db, org, user)
    repo = _make_repo(db, org)
    wf = _make_workflow_file(db, repo)
    analysis = Analysis(
        repo_id=repo.id,
        workflow_file_id=wf.id,
        content_hash=wf.content_hash,
        status=AnalysisStatus.completed,
        # Fixed in "June" so the "July" period check below can exclude it —
        # a real datetime.now() here would defeat the simulated month crossing.
        completed_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
    )
    db.add(analysis)
    db.commit()

    with patch.object(
        billing,
        "get_datetime_utc",
        return_value=datetime(2026, 6, 15, tzinfo=timezone.utc),
    ):
        analyses_used, _, _, _sub = billing._usage_for_user(db, user)
    assert analyses_used == 1

    # Simulated month crossing — the analysis completed in June no longer
    # falls within July's period.
    with patch.object(
        billing,
        "get_datetime_utc",
        return_value=datetime(2026, 7, 5, tzinfo=timezone.utc),
    ):
        analyses_used_after, _, _, _ = billing._usage_for_user(db, user)
    assert analyses_used_after == 0


def test_stripe_sync_sets_period_from_current_period_fields(db: Session) -> None:
    user = _make_user(db)
    org = _make_org(db)
    _link_owner(db, org, user)
    repo = _make_repo(db, org)
    wf = _make_workflow_file(db, repo)
    _make_fix(db, wf)

    from app.models import BillingSubscription

    sub = billing._get_or_create_subscription(db, user)
    sub.stripe_customer_id = "cus_123"
    db.add(sub)
    db.commit()

    period_start_ts = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp())
    period_end_ts = int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp())
    billing._sync_subscription(
        db,
        "cus_123",
        "sub_123",
        settings.STRIPE_PRICE_STARTER or "price_starter",
        active=True,
        current_period_start=period_start_ts,
        current_period_end=period_end_ts,
    )

    db.refresh(sub)
    assert sub.period_start == datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert sub.period_end == datetime(2026, 7, 1, tzinfo=timezone.utc)
    # Prior usage is frozen out of the freshly-set Stripe period.
    assert sub.fixes_used_baseline == 1

    refetched = db.get(BillingSubscription, sub.id)
    assert refetched is not None
    assert refetched.stripe_subscription_id == "sub_123"


# ─── GET /billing/subscription ───────────────────────────────────────────────


def test_get_subscription_creates_if_not_exists(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    # Act — first call creates the subscription
    response = client.get(
        f"{settings.API_V1_STR}/billing/subscription",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert "id" in body
    assert body["tier"] == "free"
    assert body["analyses_used"] == 0
    assert body["fixes_used"] == 0


def test_get_subscription_re_fetch_returns_same(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    # Act — call twice
    first = client.get(
        f"{settings.API_V1_STR}/billing/subscription",
        headers=superuser_token_headers,
    )
    second = client.get(
        f"{settings.API_V1_STR}/billing/subscription",
        headers=superuser_token_headers,
    )

    # Assert — same id returned both times
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


# ─── GET /billing/limits ──────────────────────────────────────────────────────


def test_get_tier_limits_returns_tier_and_limits(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    # Act
    response = client.get(
        f"{settings.API_V1_STR}/billing/limits",
        headers=superuser_token_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert "tier" in body
    assert "limits" in body
    limits = body["limits"]
    assert "analyses" in limits
    assert "fixes" in limits
    assert "repos" in limits


# ─── POST /billing/webhook/stripe ────────────────────────────────────────────


def test_stripe_webhook_returns_503_when_not_configured(
    client: TestClient,
) -> None:
    # Act — no authentication required for webhook endpoints;
    # Stripe is not configured in the test environment so the endpoint
    # should return 503 Service Unavailable.
    response = client.post(
        f"{settings.API_V1_STR}/billing/webhook/stripe",
        json={},
    )

    # Assert
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]
