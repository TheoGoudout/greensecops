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
    # When this snapshot was last verified against GitHub — refreshed by every
    # sync, including one that finds the content unchanged. It is *not* the row's
    # creation time (which is what it silently recorded while nothing wrote it),
    # and it doubles as the write-ordering cursor: a sync that resolved the ref
    # earlier than this must not overwrite the content a later one already
    # stored. See ``services/workflow_sync``.
    fetched_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    # The commit ``raw_content`` was read at. Always a resolved head, never the
    # SHA a webhook happened to carry, so "which code did we analyse?" has an
    # answer that survives the branch moving. NULL on rows last synced before
    # provenance existed; the next sync fills it in.
    source_commit_sha: str | None = Field(default=None, max_length=40)
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
