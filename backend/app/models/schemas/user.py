"""Users, auth tokens and the small shared response envelopes."""

import uuid
from datetime import datetime

from pydantic import EmailStr
from sqlmodel import Field, SQLModel

from ..db import UserBase
from ..enums import (
    UserTier,
)


class UserPublic(UserBase):
    id: uuid.UUID
    github_username: str | None = None
    tier: UserTier = UserTier.free
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


class Message(SQLModel):
    message: str


class VersionInfo(SQLModel):
    """What the API is running, for the dashboard footer to compare against.

    The dashboard and the API are promoted through different platforms —
    Cloudflare Workers and Coolify — so the dashboard cannot infer the API's
    version from its own. Reporting it here is what makes a half-finished
    promotion visible instead of showing up later as a confusing 422.
    """

    version: str
    environment: str


class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(SQLModel):
    sub: str | None = None


class PasswordRecovery(SQLModel):
    """The address to send a reset link to.

    A body rather than a path segment: an email in a URL lands in every access
    log and needs percent-encoding that callers were not doing.
    """

    email: EmailStr


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
