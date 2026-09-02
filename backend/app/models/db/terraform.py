import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship

from .mixins import (
    FileFixMixin,
    FindingMixin,
    ManualWorkMixin,
    RepoScanMixin,
    ScanTargetMixin,
)

if TYPE_CHECKING:
    from .pull_request import PullRequest
    from .repository import Repository
    from .rule import Rule


class TerraformRoot(ScanTargetMixin, table=True):
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
    # No default, unlike DockerTarget: a Terraform root is registered by hand
    # and must say where it is.
    root_path: str = Field(max_length=512)
    repository: Optional["Repository"] = Relationship(back_populates="terraform_roots")
    scans: list["TerraformScan"] = Relationship(
        back_populates="terraform_root", cascade_delete=True
    )


class TerraformScan(RepoScanMixin, table=True):
    __tablename__ = "terraform_scan"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    terraform_root_id: uuid.UUID = Field(
        foreign_key="terraform_root.id", nullable=False, ondelete="CASCADE"
    )
    terraform_root: TerraformRoot | None = Relationship(back_populates="scans")
    findings: list["TerraformFinding"] = Relationship(
        back_populates="scan", cascade_delete=True
    )


class TerraformFinding(FindingMixin, ManualWorkMixin, table=True):
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
    # the root across scans, not one scan (mirrors WorkflowFinding.workflow_file_id).
    terraform_root_id: uuid.UUID = Field(
        foreign_key="terraform_root.id", nullable=False, ondelete="CASCADE"
    )
    # The Terraform fix that addresses this finding, if one has been generated.
    # SET NULL (not CASCADE): dropping a fix must not delete the finding history
    # — mirrors ``WorkflowFinding.fix_id``.
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
    scan: TerraformScan | None = Relationship(back_populates="findings")
    # One-directional (no back_populates on Rule): findings look up their rule,
    # Rule doesn't need to know about the finding tables that reference it.
    rule: Optional["Rule"] = Relationship()
    fix: Optional["TerraformFix"] = Relationship(back_populates="findings")


class TerraformFix(FileFixMixin, table=True):
    """An LLM-generated fix for a single ``.tf`` file in a Terraform root.

    Mirrors ``WorkflowFix`` (the CI-workflow fix), but keyed to a Terraform root +
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
    terraform_root: TerraformRoot | None = Relationship()
    findings: list["TerraformFinding"] = Relationship(back_populates="fix")
    pull_request: Optional["PullRequest"] = Relationship(
        back_populates="terraform_fixes"
    )
