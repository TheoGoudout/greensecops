import secrets
from datetime import timedelta

from fastapi import APIRouter, Cookie, HTTPException, Response
from fastapi.responses import RedirectResponse
from sqlmodel import select

from app import crud
from app.api.deps import GitHubAppClientDep, SessionDep
from app.core import security
from app.core.config import settings
from app.models import Token, User, UserCreate

router = APIRouter(prefix="/auth/github", tags=["auth"])

_STATE_COOKIE = "gh_oauth_state"


@router.get("/login")
async def github_login() -> RedirectResponse:
    if not settings.GITHUB_CLIENT_ID:
        raise HTTPException(status_code=503, detail="GitHub OAuth not configured")
    state = secrets.token_urlsafe(16)
    url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={settings.GITHUB_CLIENT_ID}"
        f"&redirect_uri={settings.GITHUB_OAUTH_REDIRECT_URI}"
        "&scope=read:user,user:email"
        f"&state={state}"
    )
    response = RedirectResponse(url=url)
    # Bind the state to this browser so the callback can detect login CSRF.
    response.set_cookie(
        key=_STATE_COOKIE,
        value=state,
        max_age=600,
        httponly=True,
        secure=settings.ENVIRONMENT != "local",
        samesite="lax",
    )
    return response


@router.get("/callback")
async def github_callback(
    code: str,
    session: SessionDep,
    github_client: GitHubAppClientDep,
    response: Response,
    state: str | None = None,
    state_cookie: str | None = Cookie(
        default=None, alias=_STATE_COOKIE, include_in_schema=False
    ),
) -> Token:
    if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="GitHub OAuth not configured")

    # Server-initiated flow (/login set a state cookie): the returned state must
    # match, and the cookie is single-use. The frontend popup flow uses no cookie
    # and validates state itself.
    if state_cookie is not None:
        response.delete_cookie(_STATE_COOKIE)
        if not state or not secrets.compare_digest(state, state_cookie):
            raise HTTPException(status_code=400, detail="Invalid OAuth state")

    try:
        access_token = await github_client.exchange_oauth_code(
            code, redirect_uri=settings.GITHUB_OAUTH_REDIRECT_URI
        )
        gh_user = await github_client.get_oauth_user(access_token)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"GitHub OAuth failed: {exc}"
        ) from exc

    github_id: int = gh_user["id"]
    github_username: str = gh_user.get("login", "")
    email: str = gh_user.get("email") or f"{github_username}@users.noreply.github.com"

    # Find or create user
    user = session.exec(select(User).where(User.github_id == github_id)).first()
    if not user:
        user = session.exec(select(User).where(User.email == email)).first()

    if user:
        user.github_id = github_id
        user.github_username = github_username
        session.add(user)
        session.commit()
        session.refresh(user)
    else:
        user_in = UserCreate(
            email=email,
            password=secrets.token_urlsafe(32),
            full_name=gh_user.get("name") or github_username,
        )
        user = crud.create_user(session=session, user_create=user_in)
        user.github_id = github_id
        user.github_username = github_username
        session.add(user)
        session.commit()
        session.refresh(user)

    expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    jwt_token = security.create_access_token(user.id, expires_delta=expires)
    return Token(access_token=jwt_token)
