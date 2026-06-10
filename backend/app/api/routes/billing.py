from fastapi import APIRouter

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/subscription")
async def get_subscription() -> dict[str, str]:
    return {"message": "Get subscription - not yet implemented"}
