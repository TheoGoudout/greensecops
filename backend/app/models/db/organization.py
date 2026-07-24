import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime
from sqlmodel import Field, Relationship, SQLModel

from ..enums import FixDeliveryMode, LLMProvider, OrgRole, UserTier
from .base import get_datetime_utc

if TYPE_CHECKING:
    from .cloud import CloudAccount
    from .repository import Repository
    from .user import User


class Organization(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    github_org_id: int | None = Field(default=None, unique=True, index=True)
    installation_id: int | None = Field(default=None, unique=True, index=True)
    name: str = Field(max_length=255, index=True)
    tier: UserTier = Field(default=UserTier.free)
    default_llm_provider: LLMProvider | None = Field(default=None)
    default_llm_model: str | None = Field(default=None, max_length=255)
    fix_delivery_mode: FixDeliveryMode = Field(default=FixDeliveryMode.pr)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    members: list["OrgMember"] = Relationship(
        back_populates="organization", cascade_delete=True
    )
    repositories: list["Repository"] = Relationship(
        back_populates="organization", cascade_delete=True
    )
    cloud_accounts: list["CloudAccount"] = Relationship(
        back_populates="organization", cascade_delete=True
    )


class OrgMember(SQLModel, table=True):
    __tablename__ = "org_member"
    org_id: uuid.UUID = Field(
        foreign_key="organization.id", primary_key=True, ondelete="CASCADE"
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id", primary_key=True, ondelete="CASCADE"
    )
    role: OrgRole = Field(default=OrgRole.member)
    joined_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    organization: Organization | None = Relationship(back_populates="members")
    user: Optional["User"] = Relationship(back_populates="org_memberships")
