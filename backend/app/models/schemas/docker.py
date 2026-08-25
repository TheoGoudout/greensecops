"""The Docker engine: targets, scans, findings, fixes and build telemetry."""

import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Field, SQLModel

from ..enums import (
    Category,
    Severity,
)
from .base import (
    FileFixPublicBase,
    FilePublicBase,
    FixablePublicBase,
    RepoScanPublicBase,
    ScanTargetPublicBase,
)


class DockerTargetCreate(SQLModel):
    repo_id: uuid.UUID
    # "" means the repository root, which is what installation sync creates
    # automatically. Explicit targets are for monorepos that want each
    # sub-project graded separately.
    root_path: str = Field(default="", max_length=512)


class DockerTargetPublic(ScanTargetPublicBase):
    pass


class DockerScanPublic(RepoScanPublicBase):
    docker_target_id: uuid.UUID
    # The score is a mean of per-file scores; this is its denominator, without
    # which a grade can't be reasoned about after the fact.
    file_count: int | None = None


class DockerFindingPublic(FixablePublicBase):
    docker_target_id: uuid.UUID
    file_path: str
    # Whichever locator the rule reports: a Compose rule names the service, a
    # Dockerfile rule the build stage. Both null for a file-level rule.
    service_name: str | None = None
    stage_name: str | None = None
    # 1-based line span of the offending instruction or service block, so the
    # frontend can annotate the finding inline on the source.
    line_start: int | None = None
    line_end: int | None = None


class DockerFixPublic(FileFixPublicBase):
    docker_target_id: uuid.UUID


class DockerRuntimeFindingPublic(SQLModel):
    """One ``DockerBuildEnrichment`` dressed for the Runtime tab.

    The stored row carries only a rule slug; severity, category and title are
    resolved from the rule catalog here so the tab can sort and colour without
    a second request. All three are nullable because a Rego rule shipped
    without a seed entry in ``core/db.py`` still evaluates and still produces
    enrichments — it just has no catalog row to describe it.
    """

    id: uuid.UUID
    telemetry_id: uuid.UUID
    rule_slug: str
    rule_title: str | None = None
    severity: Severity | None = None
    category: Category | None = None
    evidence: str
    recommendation: str
    created_at: datetime | None = None


class DockerBuildTelemetryPublic(SQLModel):
    """One measured build, with the findings its measurements produced.

    ``layers`` and ``containers`` are stored as JSON text (they are
    collector-shaped and never queried relationally) and decoded here, so the
    frontend never parses a string out of a typed field.
    """

    id: uuid.UUID
    workflow_run_id: int
    image_ref: str | None = None
    dockerfile_path: str | None = None
    image_size_bytes: int | None = None
    context_size_bytes: int | None = None
    build_duration_ms: int | None = None
    cache_hit_ratio: float | None = None
    layers: list[dict[str, Any]] = Field(default_factory=list)
    containers: list[dict[str, Any]] = Field(default_factory=list)
    collected_at: datetime | None = None
    findings: list[DockerRuntimeFindingPublic] = Field(default_factory=list)


class DockerFilePublic(FilePublicBase):
    """A Dockerfile or Compose file's live source for a target.

    Not persisted (mirroring ``TerraformFilePublic``): fetched from GitHub on
    demand, so it carries no id/branch — just path and content. ``kind`` lets
    the viewer pick a syntax highlighter without re-deriving it from the name.
    """

    kind: str
