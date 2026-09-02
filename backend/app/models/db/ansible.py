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


class AnsibleProject(ScanTargetMixin, table=True):
    """A folder in a repo configured as an Ansible project to scan.

    Registered by hand like a ``TerraformRoot`` rather than auto-created like a
    ``DockerTarget``. Docker files announce themselves by filename, so a default
    repo-root target costs nothing; Ansible content is identified by the *shape*
    of a YAML document (``services/ansible/discovery.py``), which means finding
    it takes a walk of the repository rather than a filename test. Making that
    walk part of every installation sync would slow a path that is currently
    cheap, for repositories that mostly have no Ansible at all.

    One repo can hold several independent projects — a monorepo with
    ``infra/staging`` and ``infra/prod`` playbook trees — each scanned and
    graded on its own.
    """

    __tablename__ = "ansible_project"
    __table_args__ = (
        UniqueConstraint("repo_id", "root_path", name="uq_ansible_project_repo_path"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # No default, for the same reason TerraformRoot has none: the user says
    # where the project is.
    root_path: str = Field(max_length=512)
    repository: Optional["Repository"] = Relationship(back_populates="ansible_projects")
    scans: list["AnsibleScan"] = Relationship(
        back_populates="ansible_project", cascade_delete=True
    )


class AnsibleScan(RepoScanMixin, table=True):
    __tablename__ = "ansible_scan"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    ansible_project_id: uuid.UUID = Field(
        foreign_key="ansible_project.id", nullable=False, ondelete="CASCADE"
    )
    # How many files the score was averaged over. Persisted because the score
    # is a *mean of per-file scores* (`scores_per_file` on the engine spec) —
    # without the denominator a grade can't be reasoned about after the fact.
    file_count: int | None = Field(default=None)
    ansible_project: AnsibleProject | None = Relationship(back_populates="scans")
    findings: list["AnsibleFinding"] = Relationship(
        back_populates="scan", cascade_delete=True
    )


class AnsibleFinding(FindingMixin, ManualWorkMixin, table=True):
    __tablename__ = "ansible_finding"
    __table_args__ = (
        UniqueConstraint(
            "ansible_project_id",
            "fingerprint",
            name="uq_ansible_finding_project_fingerprint",
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    scan_id: uuid.UUID = Field(
        foreign_key="ansible_scan.id", nullable=False, ondelete="CASCADE"
    )
    # Denormalized off the scan: the fingerprint's uniqueness scope is the
    # project across scans, not one scan.
    ansible_project_id: uuid.UUID = Field(
        foreign_key="ansible_project.id", nullable=False, ondelete="CASCADE"
    )
    # SET NULL, not CASCADE: dropping a fix must not delete finding history.
    fix_id: uuid.UUID | None = Field(
        default=None, foreign_key="ansible_fix.id", ondelete="SET NULL"
    )
    file_path: str = Field(max_length=512)
    line_start: int | None = Field(default=None)
    line_end: int | None = Field(default=None)
    # The task's ``name:``, which is also what the fingerprint's discriminator
    # keys on. Empty for a play-level or file-level finding, and for a task that
    # has no name — which `task_missing_name` reports.
    task_name: str | None = Field(default=None, max_length=512)
    scan: AnsibleScan | None = Relationship(back_populates="findings")
    # One-directional: findings look up their rule, Rule doesn't need to know
    # about the finding tables that reference it.
    rule: Optional["Rule"] = Relationship()
    fix: Optional["AnsibleFix"] = Relationship(back_populates="findings")


class AnsibleFix(FileFixMixin, table=True):
    """An LLM-generated fix for a single Ansible file in a project.

    Keyed to a ``(ansible_project_id, file_path)`` pair rather than a persisted
    file row, exactly as ``TerraformFix`` and ``DockerFix`` are: Ansible files
    are not tracked as their own table.
    """

    __tablename__ = "ansible_fix"
    __table_args__ = (
        UniqueConstraint(
            "ansible_project_id", "file_path", name="uq_ansible_fix_project_file"
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    ansible_project_id: uuid.UUID = Field(
        foreign_key="ansible_project.id", nullable=False, ondelete="CASCADE"
    )
    ansible_project: AnsibleProject | None = Relationship()
    findings: list["AnsibleFinding"] = Relationship(back_populates="fix")
    pull_request: Optional["PullRequest"] = Relationship(back_populates="ansible_fixes")
