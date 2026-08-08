import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Form, HTTPException
from pydantic import HttpUrl
from sqlmodel import select

from app import crud
from app.api.deps import GitHubAppClientDep, SessionDep
from app.api.router import Role, RoleRouter
from app.core import security
from app.core.config import settings
from app.core.rate_limit import LIMIT_AUTH
from app.models import Token, User, UserCreate


class OAuth2AuthorizationCodeForm:
    def __init__(
        self,
        *,
        grant_type: Annotated[
            str | None,
            Form(pattern="^authorization_code$"),
        ] = None,
        code: Annotated[
            str,
            Form(),
        ],
        client_id: Annotated[
            str | None,
            Form(),
        ] = None,
        redirect_uri: Annotated[
            HttpUrl | None,
            Form(),
        ] = None,
        code_verifier: Annotated[
            str | None,
            Form(),
        ] = None,
    ):
        self.grant_type = grant_type
        self.code = code
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.code_verifier = code_verifier


router = RoleRouter(prefix="/auth/github", tags=["auth"])


@router.post("/callback", role=Role.guest, limit=LIMIT_AUTH)
async def github_callback(
    *,
    session: SessionDep,
    github_client: GitHubAppClientDep,
    form_data: Annotated[OAuth2AuthorizationCodeForm, Depends()],
) -> Token:
    if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="GitHub OAuth not configured")

    if form_data.client_id != settings.GITHUB_CLIENT_ID:
        raise HTTPException(status_code=400, detail="GitHub Client ID not matching")

    try:
        access_token = await github_client.exchange_oauth_code(
            form_data.code,
            code_verifier=form_data.code_verifier,
            redirect_uri=settings.GITHUB_OAUTH_REDIRECT_URI,
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
