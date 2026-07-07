import uuid
from collections.abc import Generator
from typing import Annotated, Any, TypeVar

import jwt
import redis.asyncio as aioredis
from fastapi import Depends, Header, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session, select

from app.core import security
from app.core.config import settings
from app.core.db import engine
from app.models import OrgMember, Repository, TokenPayload, User
from app.services.github.app_client import GitHubAppClient

_GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
_GITHUB_OIDC_AUDIENCE = "greensecops"

# PyJWKClient has built-in JWKS caching (lifespan controls TTL in seconds)
_github_jwks_client: PyJWKClient | None = None


def _get_github_jwks_client() -> PyJWKClient:
    global _github_jwks_client
    if _github_jwks_client is None:
        _github_jwks_client = PyJWKClient(
            f"{_GITHUB_OIDC_ISSUER}/.well-known/jwks",
            cache_jwk_set=True,
            lifespan=3600,
        )
    return _github_jwks_client


reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)

_optional_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token",
    auto_error=False,
)


def get_db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str, Depends(reusable_oauth2)]


def _user_from_jwt(session: Session, token: str) -> User:
    """Decode a signed app JWT and load the active user it identifies."""
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    user = session.get(User, token_data.sub)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


def get_current_user(session: SessionDep, token: TokenDep) -> User:
    return _user_from_jwt(session, token)


CurrentUser = Annotated[User, Depends(get_current_user)]

# Redis key prefix for single-use SSE tickets (see events.create_sse_ticket).
SSE_TICKET_PREFIX = "sse:ticket:"
SSE_TICKET_TTL_SECONDS = 60


async def get_current_user_sse(
    session: SessionDep,
    redis: "RedisDep",
    ticket: str | None = Query(default=None),
    token_header: str | None = Depends(_optional_oauth2),
) -> User:
    """Auth for the SSE endpoint.

    Native EventSource cannot set headers, so browsers authenticate with a
    short-lived single-use ``?ticket=`` minted from a normal (header-authed)
    request. This keeps the long-lived JWT out of URLs, access logs and
    referrers. Non-browser clients may still pass a bearer token header.
    """
    if ticket:
        redis_key = f"{SSE_TICKET_PREFIX}{ticket}"
        # Single-use: atomically fetch-and-delete so a leaked URL can't be replayed.
        user_id = await redis.getdel(redis_key)
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired SSE ticket",
            )
        user = session.get(User, uuid.UUID(user_id.decode()))
        if not user or not user.is_active:
            raise HTTPException(status_code=400, detail="Inactive user")
        return user

    if token_header:
        return _user_from_jwt(session, token_header)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )


CurrentUserSSE = Annotated[User, Depends(get_current_user_sse)]


def get_current_active_superuser(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user


async def get_redis() -> aioredis.Redis:  # type: ignore[type-arg]
    client = aioredis.from_url(settings.REDIS_URL, decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()


RedisDep = Annotated[aioredis.Redis, Depends(get_redis)]  # type: ignore[type-arg]


async def get_github_app_client(redis: RedisDep) -> GitHubAppClient:
    return GitHubAppClient(redis_client=redis)


GitHubAppClientDep = Annotated[GitHubAppClient, Depends(get_github_app_client)]


async def verify_github_oidc_token(
    authorization: str | None = Header(default=None),
) -> dict:
    """Verify a GitHub Actions OIDC JWT and return its claims.

    Raises HTTP 401 on any verification failure so telemetry endpoints
    never silently accept unauthenticated data.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing OIDC token"
        )

    token = authorization.removeprefix("Bearer ")
    try:
        client = _get_github_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        claims: dict = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=_GITHUB_OIDC_AUDIENCE,
            issuer=_GITHUB_OIDC_ISSUER,
        )
        return claims
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid OIDC token: {exc}",
        ) from exc


GitHubOidcClaims = Annotated[dict, Depends(verify_github_oidc_token)]

_T = TypeVar("_T")


def get_or_404(
    session: "Session", model: type[_T], entity_id: Any, detail: str | None = None
) -> _T:
    obj = session.get(model, entity_id)
    if not obj:
        raise HTTPException(
            status_code=404, detail=detail or f"{model.__name__} not found"
        )
    return obj


# ─── Tenant authorization ─────────────────────────────────────────────────────


def user_org_ids(session: Session, user: User) -> set[uuid.UUID]:
    """Return the set of organization ids the user is a member of."""
    return set(
        session.exec(select(OrgMember.org_id).where(OrgMember.user_id == user.id)).all()
    )


def authorize_repo(
    session: Session,
    user: User,
    repo_id: uuid.UUID,
    *,
    detail: str = "Repository not found",
) -> Repository:
    """Load a repository, enforcing that ``user`` may access it.

    Superusers bypass the tenant check. For everyone else, membership in the
    repository's organization is required. A missing repo and an unauthorized
    repo return the same 404 so tenant existence is never disclosed.
    """
    repo = session.get(Repository, repo_id)
    if not repo or (
        not user.is_superuser and repo.org_id not in user_org_ids(session, user)
    ):
        raise HTTPException(status_code=404, detail=detail)
    return repo


def require_org_membership(session: Session, user: User, org_id: uuid.UUID) -> None:
    """Raise 404 unless ``user`` is a superuser or a member of ``org_id``."""
    if user.is_superuser:
        return
    member = session.exec(
        select(OrgMember).where(
            OrgMember.org_id == org_id, OrgMember.user_id == user.id
        )
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Organization not found")
