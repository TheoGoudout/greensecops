"""The dashboard overview: per-engine stat blocks and their totals."""

import uuid
from datetime import datetime

from sqlmodel import SQLModel

from ..enums import (
    Category,
    Engine,
    OverviewSection,
    Severity,
)
from .workflow import (
    IssueCategoryStat,
)


class SeverityStat(SQLModel):
    """Open/resolved finding counts for one severity.

    Emitted for every ``Severity`` including zeros, so the frontend can
    render a fixed-segment severity bar without gap logic.
    """

    severity: Severity
    open: int
    resolved: int


class GradeStat(SQLModel):
    """How many scan targets currently hold this grade.

    Emitted for every rung of ``services.scoring.GRADE_LADDER`` in order, best
    first, plus any grade found in the data that isn't on the ladder — grades
    are free-form ``VARCHAR(8)``, so a row written before a ladder change must
    still be counted rather than silently dropped.
    """

    grade: str
    count: int


class TopRuleStat(SQLModel):
    """A rule ranked by how many open findings it accounts for."""

    rule_id: uuid.UUID
    slug: str
    title: str
    severity: Severity
    category: Category
    open: int


class EngineCoverageStat(SQLModel):
    """How much of what could be scanned actually has been.

    ``enabled`` means different things per engine — a bool column for Docker
    and Terraform targets, ``CloudAccountStatus.connected`` for a cloud
    account. The CI engine's target is a ``WorkflowFile``, which has no enable
    switch at all, so there ``enabled == total``.
    """

    total: int
    enabled: int
    scanned: int
    never_scanned: int
    # Targets whose most recent scan of *any* status failed. Independent of
    # `scanned`: a target can hold a good grade from an older completed scan
    # and still have a failing latest run.
    latest_scan_failed: int


class EngineFreshnessStat(SQLModel):
    last_completed_scan_at: datetime | None
    last_scan_at: datetime | None


class EngineScoreStat(SQLModel):
    """Average of each target's latest *completed* scan score.

    A target whose latest scan failed keeps the score of its last good scan —
    the same rule ``api/mappers/base.latest_completed_scan`` applies per
    target, so a grade here always matches the one that engine's own list
    endpoint reports.
    """

    avg_score: float | None
    grade: str | None
    scored_targets: int
    by_grade: list[GradeStat]


class EngineFindingStat(SQLModel):
    open: int
    resolved: int
    critical_open: int
    by_severity: list[SeverityStat]
    by_category: list[IssueCategoryStat]


class EngineFixPipelineStat(SQLModel):
    """Open findings bucketed by the state of the fix addressing them.

    ``unfixed`` mirrors ``list_issues(unfixed=True)``: no fix row at all, or a
    fix in one of the rejected/superseded states. The buckets are disjoint and
    sum to ``EngineFindingStat.open``.
    """

    unfixed: int
    in_progress: int
    ready: int
    delivered: int
    landed: int
    failed: int


class EngineOverview(SQLModel):
    engine: Engine
    section: OverviewSection
    label: str
    coverage: EngineCoverageStat
    freshness: EngineFreshnessStat
    score: EngineScoreStat
    findings: EngineFindingStat
    # ``None`` for the cloud engine, which has no fix pipeline at all —
    # ``CloudFinding`` carries no ``fix_id``. An all-zero object would read as
    # "nothing left to fix" rather than "not a thing here".
    fixes: EngineFixPipelineStat | None
    top_rules: list[TopRuleStat]


class OverviewTotals(SQLModel):
    """All-engine roll-up for the dashboard's summary header.

    ``avg_score`` is the unweighted mean of the per-engine averages that
    exist, not of every target: averaging targets directly would let a repo
    with forty workflow files drown out a failing cloud posture.
    """

    targets: int
    enabled_targets: int
    never_scanned_targets: int
    open_findings: int
    resolved_findings: int
    critical_open: int
    avg_score: float | None
    grade: str | None
    by_severity: list[SeverityStat]
    by_category: list[IssueCategoryStat]
    engines_with_data: int


class OverviewPublic(SQLModel):
    generated_at: datetime
    totals: OverviewTotals
    # Always all four engines, zeroed where there is nothing to report, so the
    # dashboard can render a stable set of sections instead of appearing to
    # lose one when an org has no Terraform roots yet.
    engines: list[EngineOverview]
