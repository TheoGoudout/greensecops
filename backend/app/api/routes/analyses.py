from fastapi import APIRouter

router = APIRouter(prefix="/analyses", tags=["analyses"])


@router.get("/")
async def list_analyses() -> dict[str, str]:
    return {"message": "List analyses - not yet implemented"}
