import logging
import uuid

import stripe
from fastapi import APIRouter, Header, HTTPException, Request
from sqlmodel import Session, func, select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.models import (
    Analysis,
    AnalysisStatus,
    BillingSubscription,
    BillingSubscriptionPublic,
    Fix,
    OrgMember,
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


def _user_repo_ids(session: Session, user: User) -> list[uuid.UUID]:
    org_ids = list(
        session.exec(select(OrgMember.org_id).where(OrgMember.user_id == user.id)).all()
    )
    if not org_ids:
        return []
    return list(
        session.exec(
            select(Repository.id).where(
                Repository.org_id.in_(org_ids),  # type: ignore[attr-defined]
                Repository.enabled == True,  # noqa: E712
            )
        ).all()
    )


def _usage_for_user(session: Session, user: User) -> tuple[int, int, list[uuid.UUID]]:
    """Return (analyses_used, fixes_used, repo_ids) for the user's org repos."""
    repo_ids = _user_repo_ids(session, user)
    if not repo_ids:
        return 0, 0, []
    analyses_used = (
        session.exec(
            select(func.count(Analysis.id)).where(
                Analysis.repo_id.in_(repo_ids),  # type: ignore[attr-defined]
                Analysis.status == AnalysisStatus.completed,
            )
        ).one()
        or 0
    )
    fixes_used = (
        session.exec(
            select(func.count(Fix.id))
            .join(WorkflowFile, Fix.workflow_file_id == WorkflowFile.id)  # type: ignore[arg-type]
            .where(WorkflowFile.repo_id.in_(repo_ids))  # type: ignore[attr-defined]
        ).one()
        or 0
    )
    return analyses_used, fixes_used, repo_ids


def enforce_quota(
    session: Session,
    user: User,
    kind: str,
    *,
    requested: int = 1,
    replacing: int = 0,
) -> None:
    """Raise HTTP 402 if creating ``requested`` new items would exceed the
    user's tier limit for ``kind``.

    ``kind`` is one of "analyses" or "fixes". Superusers are exempt. A ``None``
    limit means unlimited. ``replacing`` is the number of existing items the
    operation deletes and recreates (e.g. regenerating fixes), which must not
    count against the quota since the resulting total is unchanged.
    """
    if user.is_superuser:
        return
    limit = _TIER_LIMITS.get(user.tier, _TIER_LIMITS[UserTier.free]).get(kind)
    if limit is None:
        return
    analyses_used, fixes_used, _ = _usage_for_user(session, user)
    used = analyses_used if kind == "analyses" else fixes_used
    if max(used - replacing, 0) + requested > limit:
        raise HTTPException(
            status_code=402,
            detail=(
                f"{kind.capitalize()} quota reached for the {user.tier.value} tier "
                f"({limit}). Upgrade your plan to continue."
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
        event = stripe.Webhook.construct_event(
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
