import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy import DateTime
from sqlmodel import Field, Relationship, SQLModel

from ..enums import DynamicAnalysisStatus, TelemetryPhase
from .base import get_datetime_utc

if TYPE_CHECKING:
    from .repository import Repository


class TelemetryRun(SQLModel, table=True):
    __tablename__ = "telemetry_run"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repo_id: uuid.UUID = Field(
        foreign_key="repository.id", nullable=False, ondelete="CASCADE"
    )
    workflow_run_id: int = Field(index=True)
    runner_specs: str | None = Field(default=None)
    metrics: str | None = Field(default=None)
    phase: TelemetryPhase | None = Field(default=None)
    # Dynamic-analysis lifecycle for a ``completed``-phase run (owned by the
    # TelemetryMachine); NULL for ``started``-phase rows, which never enrich.
    dynamic_status: DynamicAnalysisStatus | None = Field(default=None)
    collected_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    repository: Optional["Repository"] = Relationship(back_populates="telemetry_runs")


class DynamicEnrichment(SQLModel, table=True):
    """A runtime-telemetry finding produced by dynamic analysis.

    Persisted (rather than only logged) so the recommendations a telemetry run
    surfaces — e.g. an oversized runner — are queryable and can be shown
    alongside the repo's static findings. Linked to the telemetry run that
    produced it and, when available, the latest completed analysis it enriches.
    """

    __tablename__ = "dynamic_enrichment"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repo_id: uuid.UUID = Field(
        foreign_key="repository.id", nullable=False, ondelete="CASCADE"
    )
    telemetry_run_id: uuid.UUID = Field(
        foreign_key="telemetry_run.id", nullable=False, ondelete="CASCADE"
    )
    analysis_id: uuid.UUID | None = Field(
        default=None,
        sa_column=sa.Column(
            sa.UUID,
            sa.ForeignKey("analysis.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    rule_slug: str = Field(max_length=128, index=True)
    evidence: str = Field(max_length=2048)
    recommendation: str = Field(max_length=2048)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )


class TelemetryMetricSample(SQLModel, table=True):
    __tablename__ = "telemetry_metric_sample"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repo_id: uuid.UUID = Field(
        foreign_key="repository.id", nullable=False, ondelete="CASCADE"
    )
    workflow_run_id: int = Field(index=True)
    sampled_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    cpu_percent: float | None = Field(default=None)
    ram_used_mb: float | None = Field(default=None)
    disk_used_gb: float | None = Field(default=None)
    net_bytes_sent: int | None = Field(default=None)
    net_bytes_recv: int | None = Field(default=None)
    # JSON-encoded list of the top 5-10% resource-consuming processes from
    # the proc-sampler binary (Linux runners only); NULL elsewhere.
    top_processes: str | None = Field(default=None)
