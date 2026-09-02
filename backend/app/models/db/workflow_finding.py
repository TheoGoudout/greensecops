import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from ..enums import (
    Category,
    FindingResolutionReason,
    FindingStatus,
    Severity,
)
from .base import get_datetime_utc
from .mixins import ManualWorkMixin

if TYPE_CHECKING:
    from .rule import Rule
    from .workflow_fix import WorkflowFix
    from .workflow_scan import WorkflowScan


class WorkflowFinding(ManualWorkMixin, SQLModel, table=True):
    __tablename__ = "workflow_finding"

    __table_args__ = (
        UniqueConstraint(
            "workflow_file_id", "fingerprint", name="uq_workflow_finding_wf_fingerprint"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    analysis_id: uuid.UUID = Field(
        foreign_key="workflow_scan.id", nullable=False, ondelete="CASCADE"
    )
    workflow_file_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="workflow_file.id",
        index=True,
        ondelete="CASCADE",
    )
    rule_id: uuid.UUID = Field(
        foreign_key="rule.id", nullable=False, ondelete="RESTRICT"
    )
    job: str | None = Field(default=None, max_length=255)
    step: str | None = Field(default=None, max_length=255)
    step_index: int | None = Field(default=None)
    fingerprint: str | None = Field(default=None, max_length=16, index=True)
    severity: Severity
    category: Category
    # Derived from ignored_at + resolved_at + fix_id, but persisted and kept
    # authoritative by a DB trigger (see migrations 0022/0026) so it survives
    # the fix_id ON DELETE SET NULL cascade. Applications never set it directly;
    # the trigger owns writes. To mute/unmute an issue, set/clear ignored_at.
    status: FindingStatus = Field(
        default=FindingStatus.open,
        sa_column_kwargs={"server_default": FindingStatus.open.value},
        index=True,
    )
    line_start: int | None = Field(default=None)
    line_end: int | None = Field(default=None)
    message: str = Field(max_length=2048)
    context: str | None = Field(default=None, max_length=4096)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    resolved_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    # Why the issue resolved (set with resolved_at, cleared on recur). An
    # attribute of the ``resolved`` state, not a separate state.
    resolution_reason: FindingResolutionReason | None = Field(default=None)
    # Set when a user dismisses the violation (false positive / accepted risk);
    # takes precedence in the status trigger so the issue reads ``ignored``.
    ignored_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    # `needs_manual_work` / `manual_work_note` come from ManualWorkMixin: set
    # from the fix-generation LLM's own <unfixed> report when it could not
    # resolve this issue within the workflow-file diff (too many steps, requires
    # external setup, the file's comments say the state is deliberate). Excluded
    # from the PR body's "fixed" table and from implicit bulk auto-fix
    # selection; an explicit retry on this issue/workflow clears it and gives
    # the LLM another attempt.
    fix_id: uuid.UUID | None = Field(
        default=None,
        sa_column=sa.Column(
            sa.UUID,
            sa.ForeignKey("workflow_fix.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    scan: Optional["WorkflowScan"] = Relationship(back_populates="findings")
    rule: Optional["Rule"] = Relationship(back_populates="findings")
    fix: Optional["WorkflowFix"] = Relationship(back_populates="findings")
