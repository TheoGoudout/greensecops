from fastapi import APIRouter
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.models import BillingSubscription, BillingSubscriptionPublic, UserTier

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


@router.post("/webhook/stripe", status_code=200)
async def stripe_webhook() -> dict[str, str]:
    # Stripe webhook handler — full implementation in Phase 7
    return {"status": "accepted"}
