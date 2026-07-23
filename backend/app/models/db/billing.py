import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime
from sqlmodel import Field, Relationship, SQLModel

from ..enums import UserTier
from .base import get_datetime_utc

if TYPE_CHECKING:
    from .user import User


class BillingSubscription(SQLModel, table=True):
    __tablename__ = "billing_subscription"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", unique=True, nullable=False, ondelete="CASCADE"
    )
    tier: UserTier = Field(default=UserTier.free)
    stripe_subscription_id: str | None = Field(
        default=None, max_length=255, unique=True
    )
    stripe_customer_id: str | None = Field(default=None, max_length=255)
    analyses_used: int = Field(default=0)
    fixes_used: int = Field(default=0)
    period_start: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    period_end: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    # Lifetime fix-generation sum snapshotted at the start of the current
    # period. Period usage = lifetime sum - this baseline, since the lifetime
    # counter itself is intentionally monotonic (see WorkflowFile.fix_generation_count).
    fixes_used_baseline: int = Field(default=0)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    user: Optional["User"] = Relationship(back_populates="billing_subscription")
