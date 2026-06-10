from fastapi import APIRouter

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("/")
async def list_rules() -> dict[str, str]:
    return {"message": "List rules - not yet implemented"}
