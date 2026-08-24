import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from .base import get_datetime_utc

if TYPE_CHECKING:
    from .repository import Repository
    from .workflow_fix import WorkflowFix
    from .workflow_scan import WorkflowScan


class WorkflowFile(SQLModel, table=True):
    __tablename__ = "workflow_file"
    __table_args__ = (
        UniqueConstraint(
            "repo_id", "branch", "path", name="uq_workflow_file_repo_branch_path"
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repo_id: uuid.UUID = Field(
        foreign_key="repository.id", nullable=False, ondelete="CASCADE"
    )
    # Workflow content is tracked per branch; issues hang off the per-branch
    # row, so reconciliation on one branch cannot touch another branch's state.
    branch: str = Field(default="main", max_length=255)
    path: str = Field(max_length=512)
    content_hash: str = Field(max_length=64, index=True)
    raw_content: str
    fetched_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    # Soft-delete marker: set when the path no longer exists on its branch (the
    # file was deleted/renamed in the repo). The row is kept so its resolved
    # issues and analysis history stay queryable, but it is filtered out of the
    # static-analysis view and repo grade. Cleared when the same path reappears.
    deleted_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    # Cumulative count of AI fix generations (initial + regenerate) billed
    # against this workflow file. Survives the WorkflowFix row being deleted and
    # recreated on regenerate, unlike a live-row count.
    fix_generation_count: int = Field(default=0)
    repository: Optional["Repository"] = Relationship(back_populates="workflow_files")
    scans: list["WorkflowScan"] = Relationship(
        back_populates="workflow_file",
    )
    fix: Optional["WorkflowFix"] = Relationship(back_populates="workflow_file")
