import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from ..enums import (
    AnalysisFailureKind,
    AnalysisTrigger,
    FindingResolutionReason,
    FindingStatus,
    FixStatus,
    IssueCategory,
    IssueSeverity,
    LLMProvider,
    ScanStatus,
)
from .base import get_datetime_utc

if TYPE_CHECKING:
    from .pull_request import PullRequest
    from .repository import Repository
    from .rule import Rule


class TerraformRoot(SQLModel, table=True):
    """A folder in a repo configured as a Terraform root to scan.

    One repo can have multiple roots (monorepo environments like envs/prod,
    envs/staging), each scanned and graded independently — mirrors how
    WorkflowFile tracks each workflow path separately rather than grading a
    whole repo as one blob.
    """

    __tablename__ = "terraform_root"
    __table_args__ = (
        UniqueConstraint("repo_id", "root_path", name="uq_terraform_root_repo_path"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repo_id: uuid.UUID = Field(
        foreign_key="repository.id", nullable=False, ondelete="CASCADE"
    )
    root_path: str = Field(max_length=512)
    enabled: bool = Field(default=True)
    # Polling/webhook cursor, mirrors Repository.last_polled_head_sha: the
    # default-branch head last scanned, so a push that doesn't touch this
    # root's files can be skipped cheaply in a later phase.
    last_scanned_head_sha: str | None = Field(default=None, max_length=40)
    last_scanned_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    repository: Optional["Repository"] = Relationship(back_populates="terraform_roots")
    scans: list["TerraformScan"] = Relationship(
        back_populates="terraform_root", cascade_delete=True
    )


class TerraformScan(SQLModel, table=True):
    __tablename__ = "terraform_scan"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    terraform_root_id: uuid.UUID = Field(
        foreign_key="terraform_root.id", nullable=False, ondelete="CASCADE"
    )
    status: ScanStatus = Field(
        default=ScanStatus.queued,
        sa_column_kwargs={"server_default": ScanStatus.queued.value},
    )
    triggered_by: AnalysisTrigger = Field(default=AnalysisTrigger.manual)
    branch: str | None = Field(default=None, max_length=255)
    commit_sha: str | None = Field(default=None, max_length=64)
    score: float | None = Field(default=None)
    grade: str | None = Field(default=None, max_length=8)
    error_message: str | None = Field(default=None, max_length=2048)
    failure_kind: AnalysisFailureKind | None = Field(default=None)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    completed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    terraform_root: TerraformRoot | None = Relationship(back_populates="scans")
    findings: list["TerraformFinding"] = Relationship(
        back_populates="scan", cascade_delete=True
    )


class TerraformFinding(SQLModel, table=True):
    __tablename__ = "terraform_finding"
    __table_args__ = (
        UniqueConstraint(
            "terraform_root_id",
            "fingerprint",
            name="uq_terraform_finding_root_fingerprint",
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    scan_id: uuid.UUID = Field(
        foreign_key="terraform_scan.id", nullable=False, ondelete="CASCADE"
    )
    # Denormalized off the scan: the fingerprint's uniqueness/history scope is
    # the root across scans, not one scan (mirrors Issue.workflow_file_id).
    terraform_root_id: uuid.UUID = Field(
        foreign_key="terraform_root.id", nullable=False, ondelete="CASCADE"
    )
    rule_id: uuid.UUID = Field(
        foreign_key="rule.id", nullable=False, ondelete="RESTRICT"
    )
    # The Terraform fix that addresses this finding, if one has been generated.
    # SET NULL (not CASCADE): dropping a fix must not delete the finding history
    # — mirrors ``Issue.fix_id``.
    fix_id: uuid.UUID | None = Field(
        default=None, foreign_key="terraform_fix.id", ondelete="SET NULL"
    )
    resource_address: str | None = Field(default=None, max_length=512)
    file_path: str = Field(max_length=512)
    line_start: int | None = Field(default=None)
    line_end: int | None = Field(default=None)
    # Directory-derived module locator (e.g. ``modules/storage``) and the full
    # Terraform address (``module.modules.storage.aws_s3_bucket.logs``). Both
    # nullable: root-module resources and JSON-config files carry no module
    # prefix. See ``hcl_parser.derive_module_path`` — a path heuristic, not a
    # resolved ``module {}`` invocation chain.
    module_path: str | None = Field(default=None, max_length=512)
    terraform_address: str | None = Field(default=None, max_length=1024)
    fingerprint: str = Field(max_length=16, index=True)
    severity: IssueSeverity
    category: IssueCategory
    status: FindingStatus = Field(
        default=FindingStatus.open,
        sa_column_kwargs={"server_default": FindingStatus.open.value},
        index=True,
    )
    message: str = Field(max_length=2048)
    context: str | None = Field(default=None, max_length=4096)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    resolved_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    resolution_reason: FindingResolutionReason | None = Field(default=None)
    ignored_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    scan: TerraformScan | None = Relationship(back_populates="findings")
    # One-directional (no back_populates on Rule): findings look up their rule,
    # Rule doesn't need to know about the finding tables that reference it.
    rule: Optional["Rule"] = Relationship()
    fix: Optional["TerraformFix"] = Relationship(back_populates="findings")


class TerraformFix(SQLModel, table=True):
    """An LLM-generated fix for a single ``.tf`` file in a Terraform root.

    Mirrors ``Fix`` (the CI-workflow fix), but keyed to a Terraform root +
    file path rather than a ``workflow_file_id`` — Terraform files aren't
    persisted as their own rows, so the unit a fix targets is the
    ``(terraform_root_id, file_path)`` pair. One fix per file per root; a
    repo's Terraform PR carries all its root's patched files.
    """

    __tablename__ = "terraform_fix"
    __table_args__ = (
        UniqueConstraint(
            "terraform_root_id", "file_path", name="uq_terraform_fix_root_file"
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    terraform_root_id: uuid.UUID = Field(
        foreign_key="terraform_root.id", nullable=False, ondelete="CASCADE"
    )
    file_path: str = Field(max_length=512)
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
    terraform_root: TerraformRoot | None = Relationship()
    findings: list["TerraformFinding"] = Relationship(back_populates="fix")
    pull_request: Optional["PullRequest"] = Relationship(
        back_populates="terraform_fixes"
    )
