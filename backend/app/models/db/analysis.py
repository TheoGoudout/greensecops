import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime
from sqlmodel import Field, Relationship, SQLModel

from ..enums import ScanFailureKind, ScanStatus, ScanTrigger
from .base import get_datetime_utc

if TYPE_CHECKING:
    from .issue import Issue
    from .repository import Repository
    from .workflow_file import WorkflowFile


class Analysis(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repo_id: uuid.UUID = Field(
        foreign_key="repository.id", nullable=False, ondelete="CASCADE"
    )
    workflow_file_id: uuid.UUID | None = Field(
        default=None, foreign_key="workflow_file.id", nullable=True, ondelete="CASCADE"
    )
    content_hash: str = Field(max_length=64, index=True)
    status: ScanStatus = Field(
        default=ScanStatus.running,
        sa_column_kwargs={"server_default": ScanStatus.running.value},
    )
    score: float | None = Field(default=None)
    grade: str | None = Field(default=None, max_length=8)
    triggered_by: ScanTrigger = Field(default=ScanTrigger.manual)
    branch: str | None = Field(default=None, max_length=255)
    commit_sha: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=2048)
    # Set when status is ``failed`` to say whether a ``retry`` is worthwhile
    # (transient) or futile until the input changes (permanent).
    failure_kind: ScanFailureKind | None = Field(default=None)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    completed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    repository: Optional["Repository"] = Relationship(back_populates="analyses")
    workflow_file: Optional["WorkflowFile"] = Relationship(
        back_populates="analyses",
    )
    issues: list["Issue"] = Relationship(back_populates="analysis", cascade_delete=True)
