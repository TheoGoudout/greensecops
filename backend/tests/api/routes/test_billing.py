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
        patch.object(billing, "_usage_for_user", return_value=(0, 0, [])),
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


def test_enforce_quota_replacing_does_not_count(db: Session) -> None:
    user = _make_user(db)
    org = _make_org(db)
    _link_owner(db, org, user)
    with (
        patch.dict(billing._TIER_LIMITS, {UserTier.free: {"fixes": 5}}),
        patch.object(billing, "_usage_for_user", return_value=(0, 5, [])),
    ):
        # Regenerating all 5 existing fixes keeps the total at the limit → OK.
        billing.enforce_quota(db, user, org.id, "fixes", requested=5, replacing=5)
        # One net-new fix on top of the replaced ones exceeds the limit.
        with pytest.raises(HTTPException) as exc:
            billing.enforce_quota(db, user, org.id, "fixes", requested=6, replacing=5)
    assert exc.value.status_code == 402


def test_enforce_quota_default_still_blocks_at_limit(db: Session) -> None:
    user = _make_user(db)
    org = _make_org(db)
    _link_owner(db, org, user)
    with (
        patch.dict(billing._TIER_LIMITS, {UserTier.free: {"fixes": 5}}),
        patch.object(billing, "_usage_for_user", return_value=(0, 5, [])),
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
            return_value=(0, 0, [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]),
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

    analyses_before, fixes_before, repos_before = billing._usage_for_user(db, user)
    assert analyses_before == 1
    assert fixes_before == 1
    assert repos_before == [repo.id]

    repo.enabled = False
    db.add(repo)
    db.commit()

    analyses_after, fixes_after, repos_after = billing._usage_for_user(db, user)
    assert analyses_after == 1
    assert fixes_after == 1
    assert repos_after == []  # repos_used is a live "currently enabled" count

    repo.enabled = True
    db.add(repo)
    db.commit()

    analyses_final, fixes_final, repos_final = billing._usage_for_user(db, user)
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

    analyses_first, fixes_first, repos_first = billing._usage_for_user(db, first_owner)
    assert analyses_first == 1
    assert fixes_first == 1
    assert repos_first == [repo.id]

    analyses_second, fixes_second, repos_second = billing._usage_for_user(
        db, second_owner
    )
    assert analyses_second == 0
    assert fixes_second == 0
    assert repos_second == []


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
