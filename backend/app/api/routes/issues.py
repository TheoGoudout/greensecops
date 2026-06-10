from fastapi import APIRouter

router = APIRouter(prefix="/issues", tags=["issues"])


@router.get("/")
async def list_issues() -> dict[str, str]:
    return {"message": "List issues - not yet implemented"}
