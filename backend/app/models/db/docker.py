import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from .base import get_datetime_utc
from .mixins import (
    EnrichmentMixin,
    FileFixMixin,
    FindingMixin,
    RepoScanMixin,
    ScanTargetMixin,
)

if TYPE_CHECKING:
    from .pull_request import PullRequest
    from .repository import Repository
    from .rule import Rule


class DockerTarget(ScanTargetMixin, table=True):
    """A folder in a repo whose Dockerfiles and Compose files are scanned.

    Mirrors ``TerraformRoot``: registered by hand via ``POST /docker/targets``,
    not created automatically at install time. Unlike a Terraform root, a
    Docker target's Dockerfile/Compose files are read directly from its
    ``root_path`` only — no recursive walk into subdirectories, since a
    Dockerfile in a nested build-context folder does not belong to this
    target's root the way a submodule's ``.tf`` files belong to a Terraform
    root.
    """

    __tablename__ = "docker_target"
    __table_args__ = (
        UniqueConstraint("repo_id", "root_path", name="uq_docker_target_repo_path"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # "" means the repository root. Normalized on the way in (see
    # api/routes/docker.py) so "/", "./" and "" can't create duplicate rows
    # that the unique constraint would treat as distinct.
    root_path: str = Field(default="", max_length=512)
    repository: Optional["Repository"] = Relationship(back_populates="docker_targets")
    scans: list["DockerScan"] = Relationship(
        back_populates="docker_target", cascade_delete=True
    )


class DockerScan(RepoScanMixin, table=True):
    __tablename__ = "docker_scan"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    docker_target_id: uuid.UUID = Field(
        foreign_key="docker_target.id", nullable=False, ondelete="CASCADE"
    )
    # How many files the score was averaged over. Persisted because the score
    # is a *mean of per-file scores* (see workers/tasks/docker_analysis.py) —
    # without the denominator a grade can't be reasoned about after the fact.
    file_count: int | None = Field(default=None)
    docker_target: DockerTarget | None = Relationship(back_populates="scans")
    findings: list["DockerFinding"] = Relationship(
        back_populates="scan", cascade_delete=True
    )


class DockerFinding(FindingMixin, table=True):
    __tablename__ = "docker_finding"
    __table_args__ = (
        UniqueConstraint(
            "docker_target_id",
            "fingerprint",
            name="uq_docker_finding_target_fingerprint",
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    scan_id: uuid.UUID = Field(
        foreign_key="docker_scan.id", nullable=False, ondelete="CASCADE"
    )
    # Denormalized off the scan: a fingerprint's uniqueness/history scope is
    # the target across scans, not one scan (mirrors WorkflowFinding.workflow_file_id).
    docker_target_id: uuid.UUID = Field(
        foreign_key="docker_target.id", nullable=False, ondelete="CASCADE"
    )
    # The Docker fix that addresses this finding, if one has been generated.
    # SET NULL (not CASCADE): dropping a fix must not delete finding history —
    # mirrors ``WorkflowFinding.fix_id`` and ``TerraformFinding.fix_id``.
    fix_id: uuid.UUID | None = Field(
        default=None, foreign_key="docker_fix.id", ondelete="SET NULL"
    )
    # A Dockerfile has no addressable resources, so the file *is* the unit a
    # rule fires against. The two locators below narrow it: a Compose rule
    # names the service, a Dockerfile rule the build stage. Both nullable — a
    # file-level rule (a missing OCI label, an obsolete version key) has
    # neither.
    file_path: str = Field(max_length=512)
    service_name: str | None = Field(default=None, max_length=255)
    stage_name: str | None = Field(default=None, max_length=255)
    line_start: int | None = Field(default=None)
    line_end: int | None = Field(default=None)
    scan: DockerScan | None = Relationship(back_populates="findings")
    # One-directional (no back_populates on Rule): findings look up their rule,
    # Rule doesn't need to know about the finding tables that reference it.
    rule: Optional["Rule"] = Relationship()
    fix: Optional["DockerFix"] = Relationship(back_populates="findings")


class DockerFix(FileFixMixin, table=True):
    """An LLM-generated rewrite of one Docker file in a target.

    Keyed to ``(docker_target_id, file_path)`` rather than a file row, because
    Docker files aren't persisted — the same shape as ``TerraformFix``. One fix
    per file per target; a target's PR carries all its patched files.
    """

    __tablename__ = "docker_fix"
    __table_args__ = (
        UniqueConstraint(
            "docker_target_id", "file_path", name="uq_docker_fix_target_file"
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    docker_target_id: uuid.UUID = Field(
        foreign_key="docker_target.id", nullable=False, ondelete="CASCADE"
    )
    docker_target: DockerTarget | None = Relationship()
    findings: list["DockerFinding"] = Relationship(back_populates="fix")
    pull_request: Optional["PullRequest"] = Relationship(back_populates="docker_fixes")


class DockerBuildTelemetry(SQLModel, table=True):
    """Measured facts about one image build observed in CI.

    Deliberately *not* folded into ``TelemetryRun``. That row is keyed on
    ``workflow_run_id`` and models "one runner, one run"; a workflow builds
    several images, so the cardinality is wrong and it would mix two rule
    domains into one payload. This is the parallel path, sitting beside
    ci_telemetry exactly as ci_telemetry sits beside ci_workflow.

    ``dockerfile_path`` is the join back to the *static* engine: it lets a
    measured cache-hit ratio be shown against the DockerFinding that predicted
    the problem from instruction order alone.
    """

    __tablename__ = "docker_build_telemetry"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repo_id: uuid.UUID = Field(
        foreign_key="repository.id", nullable=False, ondelete="CASCADE"
    )
    # BigInteger throughout, not the plain `int` SQLModel would map to INT4.
    # A GitHub run id already exceeds 2^31, and an image over ~2.1 GB would
    # overflow on insert — which is precisely the image `oversized_image`
    # exists to report, so the default would fail on exactly the rows that
    # matter most.
    workflow_run_id: int = Field(sa_type=sa.BigInteger, index=True)
    image_ref: str | None = Field(default=None, max_length=512)
    dockerfile_path: str | None = Field(default=None, max_length=512)
    image_size_bytes: int | None = Field(default=None, sa_type=sa.BigInteger)
    context_size_bytes: int | None = Field(default=None, sa_type=sa.BigInteger)
    build_duration_ms: int | None = Field(default=None, sa_type=sa.BigInteger)
    # Only available from the opt-in BuildKit metadata path; the zero-config
    # `docker history` collector cannot see whether a layer was cached.
    cache_hit_ratio: float | None = Field(default=None)
    # JSON-encoded per-layer detail and per-container runtime stats. Free-form
    # because both are collector-shaped and evolve with the action, and neither
    # is queried relationally.
    layers: str | None = Field(default=None)
    containers: str | None = Field(default=None)
    collected_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )


class DockerBuildEnrichment(EnrichmentMixin, table=True):
    """A measured finding produced from Docker build/runtime telemetry.

    A sibling of ``DynamicEnrichment`` rather than a generalisation of it —
    the same call the project made when ``TerraformFinding`` was added beside
    ``WorkflowFinding``.
    """

    __tablename__ = "docker_build_enrichment"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    telemetry_id: uuid.UUID = Field(
        foreign_key="docker_build_telemetry.id", nullable=False, ondelete="CASCADE"
    )
