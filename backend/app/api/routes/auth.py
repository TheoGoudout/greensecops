"""Everything that mints or resets a credential.

These four flows were spread across three modules and two tags — `/login/*`
with no prefix, `/auth/github/*`, and `/users/signup` under `users` — so a
caller looking for "how do I sign in" had to find them one at a time. They are
one namespace and one tag now; `users` is left holding only the CRUD of an
account that already exists.
"""

import secrets
from datetime import timedelta
from typing import Annotated, Any

from fastapi import Depends, Form, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import HttpUrl
from sqlmodel import select

from app import crud
from app.api.deps import CurrentUser, GitHubAppClientDep, SessionDep
from app.api.router import Role, RoleRouter
from app.core import security
from app.core.config import settings
from app.core.rate_limit import LIMIT_AUTH
from app.models import (
    Message,
    NewPassword,
    PasswordRecovery,
    Token,
    User,
    UserCreate,
    UserPublic,
    UserRegister,
    UserUpdate,
)
from app.utils import (
    generate_password_reset_token,
    generate_reset_password_email,
    send_email,
    verify_password_reset_token,
)

router = RoleRouter(prefix="/auth", tags=["auth"])


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


@router.post("/github/callback", role=Role.guest, limit=LIMIT_AUTH)
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


@router.post("/token", role=Role.guest, limit=LIMIT_AUTH)
def create_token(
    session: SessionDep,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """
    OAuth2 compatible token login, get an access token for future requests
    """
    user = crud.authenticate(
        session=session, email=form_data.username, password=form_data.password
    )
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return Token(
        access_token=security.create_access_token(
            user.id, expires_delta=access_token_expires
        )
    )


@router.post("/token/verify", role=Role.user, response_model=UserPublic)
def verify_token(current_user: CurrentUser) -> Any:
    """
    Test access token
    """
    return current_user


@router.post("/password-recovery", role=Role.guest, limit=LIMIT_AUTH)
def recover_password(
    session: SessionDep,
    body: PasswordRecovery,
) -> Message:
    """Email a password-reset link.

    The address used to be a path segment, which put it in every access log
    and needed URL-encoding nothing was doing. It is a body field now.
    """
    email = body.email
    user = crud.get_user_by_email(session=session, email=email)

    # Always return the same response to prevent email enumeration attacks
    # Only send email if user actually exists
    if user:
        password_reset_token = generate_password_reset_token(email=email)
        email_data = generate_reset_password_email(
            email_to=user.email, email=email, token=password_reset_token
        )
        send_email(
            email_to=user.email,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )
    return Message(
        message="If that email is registered, we sent a password recovery link"
    )


@router.post("/password-reset", role=Role.guest, limit=LIMIT_AUTH)
def reset_password(
    session: SessionDep,
    body: NewPassword,
) -> Message:
    """
    Reset password
    """
    email = verify_password_reset_token(token=body.token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid token")
    user = crud.get_user_by_email(session=session, email=email)
    if not user:
        # Don't reveal that the user doesn't exist - use same error as invalid token
        raise HTTPException(status_code=400, detail="Invalid token")
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    user_in_update = UserUpdate(password=body.new_password)
    crud.update_user(
        session=session,
        db_user=user,
        user_in=user_in_update,
    )
    return Message(message="Password updated successfully")


@router.post("/register", role=Role.guest, limit=LIMIT_AUTH, response_model=UserPublic)
def register_user(
    session: SessionDep,
    user_in: UserRegister,
) -> Any:
    """
    Create new user without the need to be logged in.
    """
    user = crud.get_user_by_email(session=session, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system",
        )
    user_create = UserCreate.model_validate(user_in)
    user = crud.create_user(session=session, user_create=user_create)
    return user
