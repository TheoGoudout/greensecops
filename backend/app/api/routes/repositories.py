from fastapi import APIRouter

router = APIRouter(prefix="/repositories", tags=["repositories"])


@router.get("/")
async def list_repositories() -> dict[str, str]:
    return {"message": "List repositories - not yet implemented"}
