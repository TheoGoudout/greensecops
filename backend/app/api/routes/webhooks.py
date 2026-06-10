from fastapi import APIRouter, Request

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/github")
async def github_webhook(request: Request) -> dict[str, str]:
    return {"message": "GitHub webhook - not yet implemented"}
