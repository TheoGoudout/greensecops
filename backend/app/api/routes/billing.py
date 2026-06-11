import logging

import stripe
from fastapi import APIRouter, Header, HTTPException, Request
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.models import BillingSubscription, BillingSubscriptionPublic, User, UserTier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

_TIER_LIMITS: dict[str, dict[str, int | None]] = {
    UserTier.free: {"analyses": 50, "fixes": 5, "repos": 3},
    UserTier.starter: {"analyses": 500, "fixes": 50, "repos": 10},
    UserTier.pro: {"analyses": None, "fixes": 500, "repos": None},
    UserTier.ultimate: {"analyses": None, "fixes": None, "repos": None},
    UserTier.open_source: {"analyses": None, "fixes": 20, "repos": 5},
}


@router.get("/subscription", response_model=BillingSubscriptionPublic)
def get_subscription(
    session: SessionDep,
    current_user: CurrentUser,
) -> BillingSubscription:
    sub = session.exec(
        select(BillingSubscription).where(
            BillingSubscription.user_id == current_user.id
        )
    ).first()
    if not sub:
        # Auto-create free tier subscription
        sub = BillingSubscription(user_id=current_user.id, tier=UserTier.free)
        session.add(sub)
        session.commit()
        session.refresh(sub)
    return sub


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
