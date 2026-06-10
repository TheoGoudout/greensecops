from fastapi import APIRouter

router = APIRouter(prefix="/fixes", tags=["fixes"])


@router.get("/")
async def list_fixes() -> dict[str, str]:
    return {"message": "List fixes - not yet implemented"}
