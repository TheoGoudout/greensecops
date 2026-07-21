import logging
import uuid

import stripe
from fastapi import APIRouter, Header, HTTPException, Request
from sqlmodel import Session, col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.models import (
    Analysis,
    AnalysisStatus,
    BillingSubscription,
    BillingSubscriptionPublic,
    Fix,
    OrgMember,
    OrgRole,
    Repository,
    User,
    UserTier,
    WorkflowFile,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

_TIER_LIMITS: dict[str, dict[str, int | None]] = {
    UserTier.free: {"analyses": 50, "fixes": 5, "repos": 3},
    UserTier.starter: {"analyses": 500, "fixes": 50, "repos": 10},
    UserTier.pro: {"analyses": None, "fixes": 500, "repos": None},
    UserTier.ultimate: {"analyses": None, "fixes": None, "repos": None},
    UserTier.open_source: {"analyses": None, "fixes": 20, "repos": 5},
}


# Tiers permitted to enable auto-fix (automatic PR delivery). ``free`` is
# excluded — it is a paid feature. A platform superuser bypasses this gate
# entirely, which is also how a sponsored open-source repo gets auto-fix
# without upgrading the whole org's tier.
_AUTO_FIX_TIERS: frozenset[UserTier] = frozenset(
    {UserTier.starter, UserTier.pro, UserTier.ultimate, UserTier.open_source}
)


def _org_billing_owner(session: Session, org_id: uuid.UUID) -> User | None:
    """Return the user whose tier/subscription an org's usage counts against.

    The billing owner is the earliest-joined ``owner`` member of the org.
    Every org gets an owner member the moment it's linked (``add_org_owner``),
    but a shared GitHub org can end up with several owner members if more than
    one person links it — ordering by ``joined_at`` keeps that resolution
    stable instead of arbitrary, so later members don't pool usage into (or
    borrow quota from) their own separate personal tier.
    """
    member = session.exec(
        select(OrgMember)
        .where(OrgMember.org_id == org_id, OrgMember.role == OrgRole.owner)
        .order_by(col(OrgMember.joined_at), col(OrgMember.user_id))
    ).first()
    if member is None:
        return None
    return session.get(User, member.user_id)


def _billing_owner_org_ids(session: Session, user_id: uuid.UUID) -> list[uuid.UUID]:
    """Return org ids whose usage counts against ``user_id``'s tier.

    Restricted to orgs where this user is the resolved billing owner, so a
    user merely riding along as a later owner/member of someone else's org
    doesn't inherit that org's usage.
    """
    owned_org_ids = session.exec(
        select(OrgMember.org_id).where(
            OrgMember.user_id == user_id, OrgMember.role == OrgRole.owner
        )
    ).all()
    return [
        org_id
        for org_id in owned_org_ids
        if (owner := _org_billing_owner(session, org_id)) is not None
        and owner.id == user_id
    ]


def _usage_for_user(session: Session, user: User) -> tuple[int, int, list[uuid.UUID]]:
    """Return (analyses_used, fixes_used, enabled_repo_ids) for ``user``.

    ``analyses_used`` and ``fixes_used`` count every repo ever attached to an
    org this user is the billing owner of, enabled or not — disabling a repo
    doesn't erase its history, so it must not erase its usage either.
    ``enabled_repo_ids`` (backing the "repos" limit and display count) is the
    live, current set of enabled repos — a capacity metric, not a cumulative
    one, so it's expected to change as repos are toggled.
    """
    org_ids = _billing_owner_org_ids(session, user.id)
    if not org_ids:
        return 0, 0, []
    all_repo_ids = list(
        session.exec(
            select(Repository.id).where(Repository.org_id.in_(org_ids))  # type: ignore[attr-defined]
        ).all()
    )
    enabled_repo_ids = list(
        session.exec(
            select(Repository.id).where(
                Repository.org_id.in_(org_ids),  # type: ignore[attr-defined]
                Repository.enabled == True,  # noqa: E712
            )
        ).all()
    )
    if not all_repo_ids:
        return 0, 0, []
    analyses_used = (
        session.exec(
            select(func.count(col(Analysis.id))).where(
                col(Analysis.repo_id).in_(all_repo_ids),
                Analysis.status == AnalysisStatus.completed,
            )
        ).one()
        or 0
    )
    fixes_used = (
        session.exec(
            select(func.count(col(Fix.id)))
            .join(WorkflowFile, Fix.workflow_file_id == WorkflowFile.id)  # type: ignore[arg-type]
            .where(col(WorkflowFile.repo_id).in_(all_repo_ids))
        ).one()
        or 0
    )
    return analyses_used, fixes_used, enabled_repo_ids


def enforce_quota(
    session: Session,
    current_user: User,
    org_id: uuid.UUID,
    kind: str,
    *,
    requested: int = 1,
    replacing: int = 0,
) -> None:
    """Raise HTTP 402 if creating ``requested`` new items would exceed the
    tier limit for ``kind`` of ``org_id``'s billing owner.

    ``kind`` is one of "analyses", "fixes", or "repos". ``current_user`` being
    a superuser exempts the call outright (admin override); the org's billing
    owner being a superuser exempts it too. A ``None`` limit means unlimited.
    ``replacing`` is the number of existing items the operation deletes and
    recreates (e.g. regenerating fixes), which must not count against the
    quota since the resulting total is unchanged.

    Usage is measured against the org's billing owner rather than
    ``current_user`` directly, so a non-owner teammate triggering an action on
    a shared org still debits and is blocked by the real billing owner's
    quota instead of silently bypassing it.
    """
    if current_user.is_superuser:
        return
    user = _org_billing_owner(session, org_id)
    if user is None or user.is_superuser:
        return
    limit = _TIER_LIMITS.get(user.tier, _TIER_LIMITS[UserTier.free]).get(kind)
    if limit is None:
        return
    analyses_used, fixes_used, enabled_repo_ids = _usage_for_user(session, user)
    used = {
        "analyses": analyses_used,
        "fixes": fixes_used,
        "repos": len(enabled_repo_ids),
    }[kind]
    if max(used - replacing, 0) + requested > limit:
        raise HTTPException(
            status_code=402,
            detail=(
                f"{kind.capitalize()} quota reached for the {user.tier.value} tier "
                f"({limit}). Upgrade your plan to continue."
            ),
        )


def enforce_auto_fix_enable(
    session: Session,
    current_user: User,
    org_id: uuid.UUID,
) -> None:
    """Raise HTTP 402 unless auto-fix may be enabled for ``org_id``.

    Auto-fix (automatic PR delivery) is a paid feature: only a platform
    superuser or an org whose billing owner is on a paid tier may enable it.
    A superuser caller (or superuser billing owner) is exempt — that is the
    mechanism for force-enabling auto-fix on a sponsored open-source repo
    without upgrading its org's tier. Measured against the org's billing owner,
    like ``enforce_quota``, so a non-owner teammate can't bypass the gate.
    """
    if current_user.is_superuser:
        return
    user = _org_billing_owner(session, org_id)
    if user is None or user.is_superuser:
        return
    if user.tier not in _AUTO_FIX_TIERS:
        raise HTTPException(
            status_code=402,
            detail=(
                "Auto-fix is available on paid plans. Upgrade your plan to enable it."
            ),
        )


@router.get("/subscription", response_model=BillingSubscriptionPublic)
def get_subscription(
    session: SessionDep,
    current_user: CurrentUser,
) -> BillingSubscriptionPublic:
    sub = session.exec(
        select(BillingSubscription).where(
            BillingSubscription.user_id == current_user.id
        )
    ).first()
    if not sub:
        sub = BillingSubscription(user_id=current_user.id, tier=UserTier.free)
        session.add(sub)
        session.commit()
        session.refresh(sub)

    analyses_used, fixes_used, repo_ids = _usage_for_user(session, current_user)

    return BillingSubscriptionPublic(
        id=sub.id,
        tier=sub.tier,
        analyses_used=analyses_used,
        fixes_used=fixes_used,
        repos_used=len(repo_ids),
        period_start=sub.period_start,
        period_end=sub.period_end,
    )


@router.get("/limits")
def get_tier_limits(current_user: CurrentUser) -> dict[str, object]:
    tier = current_user.tier
    limits = _TIER_LIMITS.get(tier, _TIER_LIMITS[UserTier.free])
    return {
        "tier": tier,
        "limits": limits,
    }


def _price_to_tier(price_id: str) -> UserTier | None:
    mapping = {
        settings.STRIPE_PRICE_STARTER: UserTier.starter,
        settings.STRIPE_PRICE_PRO: UserTier.pro,
        settings.STRIPE_PRICE_ULTIMATE: UserTier.ultimate,
    }
    return mapping.get(price_id)


def _sync_subscription(
    session: SessionDep,
    customer_id: str,
    stripe_sub_id: str,
    price_id: str,
    active: bool,
) -> None:
    tier = _price_to_tier(price_id) if active else UserTier.free
    if tier is None:
        logger.warning("Unknown Stripe price_id %s — defaulting to free", price_id)
        tier = UserTier.free

    sub = session.exec(
        select(BillingSubscription).where(
            BillingSubscription.stripe_customer_id == customer_id
        )
    ).first()
    if not sub:
        sub = session.exec(
            select(BillingSubscription).where(
                BillingSubscription.stripe_subscription_id == stripe_sub_id
            )
        ).first()
    if not sub:
        logger.warning("No subscription found for customer %s", customer_id)
        return

    sub.tier = tier
    sub.stripe_subscription_id = stripe_sub_id
    sub.stripe_customer_id = customer_id
    session.add(sub)

    user = session.get(User, sub.user_id)
    if user:
        user.tier = tier
        session.add(user)

    session.commit()


@router.post("/webhook/stripe", status_code=200)
async def stripe_webhook(
    request: Request,
    session: SessionDep,
    stripe_signature: str | None = Header(default=None, alias="stripe-signature"),
) -> dict[str, str]:
    if not settings.STRIPE_SECRET_KEY or not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Stripe not configured")

    payload = await request.body()
    try:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        event = stripe.Webhook.construct_event(  # type: ignore[no-untyped-call]
            payload, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    event_type: str = event["type"]
    data = event["data"]["object"]

    if event_type in ("customer.subscription.created", "customer.subscription.updated"):
        customer_id: str = data["customer"]
        stripe_sub_id: str = data["id"]
        active: bool = data["status"] in ("active", "trialing")
        items = data.get("items", {}).get("data", [])
        price_id: str = items[0]["price"]["id"] if items else ""
        _sync_subscription(session, customer_id, stripe_sub_id, price_id, active)

    elif event_type == "customer.subscription.deleted":
        customer_id = data["customer"]
        stripe_sub_id = data["id"]
        _sync_subscription(session, customer_id, stripe_sub_id, "", active=False)

    elif event_type == "checkout.session.completed":
        customer_id = data.get("customer", "")
        stripe_sub_id = data.get("subscription", "")
        if customer_id and stripe_sub_id:
            sub = session.exec(
                select(BillingSubscription).where(
                    BillingSubscription.stripe_subscription_id == stripe_sub_id
                )
            ).first()
            if sub:
                sub.stripe_customer_id = customer_id
                session.add(sub)
                session.commit()

    else:
        logger.debug("Unhandled Stripe event type: %s", event_type)

    return {"status": "ok"}
