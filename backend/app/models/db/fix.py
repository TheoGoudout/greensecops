import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy import DateTime
from sqlmodel import Field, Relationship, SQLModel

from ..enums import FixStatus, LLMProvider
from .base import get_datetime_utc

if TYPE_CHECKING:
    from .issue import Issue
    from .pull_request import PullRequest
    from .workflow_file import WorkflowFile


class Fix(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_file_id: uuid.UUID = Field(
        foreign_key="workflow_file.id", unique=True, nullable=False, ondelete="CASCADE"
    )
    pr_id: uuid.UUID | None = Field(
        default=None,
        sa_column=sa.Column(
            sa.UUID,
            sa.ForeignKey("pull_request.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    llm_provider: LLMProvider
    llm_model: str = Field(max_length=255)
    prompt_tokens: int | None = Field(default=None)
    completion_tokens: int | None = Field(default=None)
    langsmith_run_id: str | None = Field(default=None, max_length=255)
    status: FixStatus = Field(default=FixStatus.pending)
    full_content: str | None = Field(default=None)
    error_message: str | None = Field(default=None, max_length=2048)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    delivered_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    workflow_file: Optional["WorkflowFile"] = Relationship(back_populates="fix")
    issues: list["Issue"] = Relationship(back_populates="fix")
    pull_request: Optional["PullRequest"] = Relationship(back_populates="fixes")
