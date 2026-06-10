from fastapi import APIRouter

router = APIRouter(prefix="/auth/github", tags=["auth"])


@router.get("/login")
async def github_login() -> dict[str, str]:
    return {"message": "GitHub OAuth login - not yet implemented"}


@router.get("/callback")
async def github_callback(code: str, state: str | None = None) -> dict[str, str]:
    return {"message": "GitHub OAuth callback - not yet implemented", "code": code}
