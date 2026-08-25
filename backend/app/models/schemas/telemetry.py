"""CI telemetry runs and the dynamic-analysis findings enriched from them."""

import uuid
from datetime import datetime
from typing import Any

from sqlmodel import SQLModel

from ..enums import (
    DynamicAnalysisStatus,
    TelemetryPhase,
)


class DynamicEnrichmentPublic(SQLModel):
    """A runtime-telemetry finding, exposed for the frontend.

    Deliberately thinner than ``IssuePublic``: enrichments carry no severity,
    category, status/lifecycle, line numbers, or fix linkage, so they are
    presented as their own "Runtime findings" class rather than merged into the
    static issue list.
    """

    id: uuid.UUID
    telemetry_run_id: uuid.UUID
    workflow_run_id: int | None = None
    rule_slug: str
    evidence: str
    recommendation: str
    created_at: datetime | None = None


class TelemetryRunPublic(SQLModel):
    id: uuid.UUID
    workflow_run_id: int
    phase: TelemetryPhase | None = None
    dynamic_status: DynamicAnalysisStatus | None = None
    runner_specs: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    collected_at: datetime | None = None
    enrichments: list[DynamicEnrichmentPublic] = []


class TelemetryAveragePublic(SQLModel):
    """Averaged telemetry across a repo's runs.

    Sample-derived fields are averaged over ``TelemetryMetricSample`` rows;
    run-derived fields (``avg_ram_percent``, ``avg_vcpus``) come from the
    per-run ``metrics``/``runner_specs`` JSON. Any field is ``None`` when no
    data supports it.
    """

    run_count: int = 0
    sample_count: int = 0
    avg_cpu_percent: float | None = None
    avg_ram_used_mb: float | None = None
    avg_ram_percent: float | None = None
    avg_disk_used_gb: float | None = None
    avg_net_bytes_sent: float | None = None
    avg_net_bytes_recv: float | None = None
    avg_vcpus: float | None = None


class TelemetrySummaryPublic(SQLModel):
    average: TelemetryAveragePublic
    runs: list[TelemetryRunPublic] = []
