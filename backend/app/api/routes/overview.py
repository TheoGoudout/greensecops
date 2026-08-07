"""The cross-engine dashboard overview.

Four analysis engines — CI workflows, Docker, Terraform and cloud posture —
each answer the same six questions: how much is covered, how fresh is it, what
does it score, what is open, what is being fixed, and which rules hurt most.
Before this endpoint the dashboard could only ask them of CI, because
``/issues/stats`` is the only aggregate the API had and the other three engines
expose findings solely per-target (``GET /docker-targets/{id}/findings``), which
an org-wide page cannot fan out to without an N+1.

The engines differ in their nouns but not in their *columns* — that is what
``models/db/mixins.py`` asserts, and it is what lets the aggregation below be
written once against a descriptor rather than four times against four models.

Deliberately *not* built on ``services.engines.EngineSpec``: that abstraction
answers "how do I generate and deliver a fix", excludes cloud and CI by name in
its own docstring, and carries branch/label fields this module never reads.
Two small descriptors beat one that is half-null for half its members.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import and_, case, func, true
from sqlmodel import Session, col, select

from app.api.deps import CurrentUser, SessionDep, authorize_org, user_org_ids
from app.models import (
    Analysis,
    AnalysisStatus,
    CloudAccount,
    CloudAccountStatus,
    CloudFinding,
    CloudScan,
    DockerFinding,
    DockerFix,
    DockerScan,
    DockerTarget,
    EngineCoverageStat,
    EngineFindingStat,
    EngineFixPipelineStat,
    EngineFreshnessStat,
    EngineOverview,
    EngineScoreStat,
    Fix,
    FixStatus,
    GradeStat,
    Issue,
    IssueCategory,
    IssueCategoryStat,
    IssueSeverity,
    OverviewEngineKey,
    OverviewPublic,
    OverviewSection,
    OverviewTotals,
    Repository,
    Rule,
    ScanStatus,
    SeverityStat,
    TerraformFinding,
    TerraformFix,
    TerraformRoot,
    TerraformScan,
    TopRuleStat,
    WorkflowFile,
)
from app.services.scoring import GRADE_LADDER, score_to_grade
from app.services.state_machines import IN_FLIGHT_STATUSES

router = APIRouter(prefix="/overview", tags=["overview"])


# ─── Engine descriptor ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _OverviewEngine:
    """The per-engine nouns the aggregation below needs, as column objects.

    Column objects rather than attribute-name strings so mypy and SQLModel can
    still see the types; the alternative degrades the whole module to
    stringly-typed ``getattr`` access for the sake of four lines.
    """

    key: OverviewEngineKey
    section: OverviewSection
    label: str

    target_model: type[Any]
    scan_model: type[Any]
    finding_model: type[Any]
    # ``None`` for cloud: CloudFinding carries no fix_id, there is no pipeline.
    fix_model: type[Any] | None

    scan_target_fk: Any
    scan_completed: Any
    scan_failed: Any
    # CI orders its "latest scan" by completed_at first, everyone else by
    # created_at. Not a stylistic difference — see `_latest_scan_order`.
    scan_orders_by_completed_at: bool

    finding_target_fk: Any
    finding_scan_fk: Any
    # Predicate marking a target as "switched on". Not a plain column: Docker
    # and Terraform have a bool, cloud has a status enum, CI has neither.
    target_enabled: Any | None
    # (model, onclause) the target query must join for `target_extra` to work.
    target_join: tuple[type[Any], Any] | None
    target_extra: Any | None


def _repo_scope(org_ids: set[uuid.UUID]) -> Any:
    """Repository ids belonging to any of ``org_ids``, as a subquery."""
    return select(Repository.id).where(col(Repository.org_id).in_(org_ids))


def _engine_specs() -> list[_OverviewEngine]:
    return [
        _OverviewEngine(
            key=OverviewEngineKey.ci,
            section=OverviewSection.ci,
            label="CI workflows",
            target_model=WorkflowFile,
            scan_model=Analysis,
            finding_model=Issue,
            fix_model=Fix,
            scan_target_fk=Analysis.workflow_file_id,
            scan_completed=AnalysisStatus.completed,
            scan_failed=AnalysisStatus.failed,
            scan_orders_by_completed_at=True,
            finding_target_fk=Issue.workflow_file_id,
            finding_scan_fk=Issue.analysis_id,
            # A workflow file has no enable switch; `enabled` falls back to
            # `total` for this engine.
            target_enabled=None,
            target_join=(Repository, WorkflowFile.repo_id == Repository.id),
            # Same scoping compute_avg_scores_batch applies (scoring.py:113-118):
            # without it, feature-branch and deleted workflow files inflate
            # every CI count on the dashboard.
            target_extra=and_(
                col(WorkflowFile.branch) == Repository.default_branch,
                col(WorkflowFile.deleted_at).is_(None),
            ),
        ),
        _OverviewEngine(
            key=OverviewEngineKey.docker,
            section=OverviewSection.docker,
            label="Docker",
            target_model=DockerTarget,
            scan_model=DockerScan,
            finding_model=DockerFinding,
            fix_model=DockerFix,
            scan_target_fk=DockerScan.docker_target_id,
            scan_completed=ScanStatus.completed,
            scan_failed=ScanStatus.failed,
            scan_orders_by_completed_at=False,
            finding_target_fk=DockerFinding.docker_target_id,
            finding_scan_fk=DockerFinding.scan_id,
            target_enabled=col(DockerTarget.enabled).is_(True),
            target_join=None,
            target_extra=None,
        ),
        _OverviewEngine(
            key=OverviewEngineKey.terraform,
            section=OverviewSection.infra,
            label="Terraform",
            target_model=TerraformRoot,
            scan_model=TerraformScan,
            finding_model=TerraformFinding,
            fix_model=TerraformFix,
            scan_target_fk=TerraformScan.terraform_root_id,
            scan_completed=ScanStatus.completed,
            scan_failed=ScanStatus.failed,
            scan_orders_by_completed_at=False,
            finding_target_fk=TerraformFinding.terraform_root_id,
            finding_scan_fk=TerraformFinding.scan_id,
            target_enabled=col(TerraformRoot.enabled).is_(True),
            target_join=None,
            target_extra=None,
        ),
        _OverviewEngine(
            key=OverviewEngineKey.cloud,
            section=OverviewSection.infra,
            label="Cloud posture",
            target_model=CloudAccount,
            scan_model=CloudScan,
            finding_model=CloudFinding,
            fix_model=None,
            scan_target_fk=CloudScan.cloud_account_id,
            scan_completed=ScanStatus.completed,
            scan_failed=ScanStatus.failed,
            scan_orders_by_completed_at=False,
            finding_target_fk=CloudFinding.cloud_account_id,
            finding_scan_fk=CloudFinding.scan_id,
            target_enabled=CloudAccount.status == CloudAccountStatus.connected,
            target_join=None,
            target_extra=None,
        ),
    ]


def _target_org_filter(spec: _OverviewEngine, org_ids: set[uuid.UUID]) -> Any:
    """Restrict an engine's *targets* to the given orgs."""
    if spec.key is OverviewEngineKey.cloud:
        # The only org-scoped target: a cloud account hangs off an org, not
        # a repository.
        return col(CloudAccount.org_id).in_(org_ids)
    return col(spec.target_model.repo_id).in_(_repo_scope(org_ids))


def _finding_org_filter(spec: _OverviewEngine, org_ids: set[uuid.UUID]) -> Any:
    """Restrict an engine's *findings* to the given orgs.

    A predicate rather than a join so it composes with ``group_by`` without
    fanning out rows — the same reasoning behind ``get_issue_stats``' scoping.
    """
    if spec.key is OverviewEngineKey.cloud:
        return col(CloudFinding.cloud_account_id).in_(
            select(CloudAccount.id).where(col(CloudAccount.org_id).in_(org_ids))
        )
    if spec.key is OverviewEngineKey.ci:
        # Issue has no repo column of its own; it reaches one through Analysis,
        # which is why get_issue_stats joins Analysis to scope at all.
        return col(Issue.analysis_id).in_(
            select(Analysis.id).where(col(Analysis.repo_id).in_(_repo_scope(org_ids)))
        )
    return col(spec.finding_target_fk).in_(
        select(spec.target_model.id).where(
            col(spec.target_model.repo_id).in_(_repo_scope(org_ids))
        )
    )


def _latest_scan_order(spec: _OverviewEngine) -> list[Any]:
    """How to pick a target's most recent scan.

    Two orderings already exist in this codebase and they disagree:
    ``mappers/base.latest_completed_scan`` takes ``max(created_at)``, while
    ``get_issue_stats``' correlated subquery orders by ``completed_at`` first.
    Rather than silently picking one, each engine keeps the ordering its own
    endpoints already use — so this endpoint's Docker grade always matches what
    ``GET /docker-targets/`` reports, and its CI counts always match
    ``GET /issues/stats``.
    """
    order = [col(spec.scan_model.created_at).desc()]
    if spec.scan_orders_by_completed_at:
        order.insert(0, col(spec.scan_model.completed_at).desc().nulls_last())
    return order


def _latest_only_predicate(spec: _OverviewEngine) -> Any:
    """Pin a finding to the latest completed scan of its own target.

    The generic form of ``get_issue_stats``' subquery (issues.py:181-193), and
    it must stay byte-for-byte equivalent for CI or the dashboard's two halves
    disagree about the same number.

    Docker/Terraform/Cloud do not strictly need it — ``resolve_stale_findings``
    resolves any finding a scan stopped seeing, so live rows are already
    current — but applying it uniformly also drops findings still pointing at a
    superseded scan, which is the same intent.
    """
    latest = (
        select(spec.scan_model.id)
        .where(spec.scan_target_fk == spec.finding_target_fk)
        .where(spec.scan_model.status == spec.scan_completed)
        .order_by(*_latest_scan_order(spec))
        .limit(1)
        .correlate(spec.finding_model)
        .scalar_subquery()
    )
    return spec.finding_scan_fk == latest


def _latest_scan_subquery(spec: _OverviewEngine, *, completed_only: bool) -> Any:
    """One row per target: its most recent scan.

    A window function rather than a correlated subquery because the coverage
    query touches every target in the org — this is one sorted pass over the
    scan table instead of an index probe per target. (``DISTINCT ON`` would be
    tighter still, but it is Postgres-only and appears nowhere else here.)
    """
    query = select(  # type: ignore[call-overload]
        spec.scan_target_fk.label("target_id"),
        col(spec.scan_model.status).label("status"),
        col(spec.scan_model.score).label("score"),
        col(spec.scan_model.grade).label("grade"),
        col(spec.scan_model.completed_at).label("completed_at"),
        col(spec.scan_model.created_at).label("created_at"),
        func.row_number()
        .over(
            partition_by=spec.scan_target_fk,
            order_by=_latest_scan_order(spec),
        )
        .label("rn"),
    )
    if completed_only:
        query = query.where(spec.scan_model.status == spec.scan_completed)
    inner = query.subquery()
    return select(inner).where(inner.c.rn == 1).subquery()


# ─── Per-engine aggregates ────────────────────────────────────────────────────


def _coverage_and_score(
    session: Session, spec: _OverviewEngine, org_ids: set[uuid.UUID] | None
) -> tuple[EngineCoverageStat, EngineFreshnessStat, EngineScoreStat]:
    """Coverage, freshness and score in one grouped query.

    Grouped by the latest completed scan's grade so the grade distribution
    falls out of the same pass; every scalar is folded from the group rows.
    """
    latest_completed = _latest_scan_subquery(spec, completed_only=True)
    latest_any = _latest_scan_subquery(spec, completed_only=False)

    query = select(spec.target_model.id)
    if spec.target_join is not None:
        query = query.join(*spec.target_join)
    if spec.target_extra is not None:
        query = query.where(spec.target_extra)
    if org_ids is not None:
        query = query.where(_target_org_filter(spec, org_ids))

    enabled = spec.target_enabled if spec.target_enabled is not None else true()
    query = query.outerjoin(
        latest_completed, latest_completed.c.target_id == spec.target_model.id
    ).outerjoin(latest_any, latest_any.c.target_id == spec.target_model.id)

    grouped = query.with_only_columns(
        latest_completed.c.grade.label("grade"),
        func.count().label("total"),
        func.sum(case((enabled, 1), else_=0)).label("enabled"),
        # count(<col>) counts non-null LEFT JOIN matches, i.e. targets with at
        # least one completed scan — NOT count(*), which counts every target.
        func.count(latest_completed.c.target_id).label("scanned"),
        func.sum(case((latest_any.c.status == spec.scan_failed, 1), else_=0)).label(
            "latest_failed"
        ),
        # SUM/COUNT rather than AVG: the rows are grade groups, and averaging
        # per-group averages would weight a lone A+++ like a hundred Bs.
        func.sum(latest_completed.c.score).label("score_sum"),
        func.count(latest_completed.c.score).label("score_count"),
        func.max(latest_completed.c.completed_at).label("last_completed_scan_at"),
        func.max(latest_any.c.created_at).label("last_scan_at"),
    ).group_by(latest_completed.c.grade)

    # session.execute(), not session.exec(): a SelectOfScalar keeps scalarizing
    # after with_only_columns and would drop every column but the first
    # (issues.py:204-207 documents the same trap).
    rows = session.execute(grouped).all()

    total = enabled_count = scanned = latest_failed = score_count = 0
    score_sum = 0.0
    last_completed_scan_at: datetime | None = None
    last_scan_at: datetime | None = None
    grade_counts: dict[str, int] = defaultdict(int)

    for row in rows:
        total += row.total or 0
        enabled_count += int(row.enabled or 0)
        scanned += row.scanned or 0
        latest_failed += int(row.latest_failed or 0)
        score_sum += float(row.score_sum or 0.0)
        score_count += row.score_count or 0
        if row.grade is not None:
            grade_counts[row.grade] += row.scanned or 0
        last_completed_scan_at = _max_dt(
            last_completed_scan_at, row.last_completed_scan_at
        )
        last_scan_at = _max_dt(last_scan_at, row.last_scan_at)

    avg_score = round(score_sum / score_count, 1) if score_count else None

    coverage = EngineCoverageStat(
        total=total,
        enabled=enabled_count,
        scanned=scanned,
        never_scanned=total - scanned,
        latest_scan_failed=latest_failed,
    )
    freshness = EngineFreshnessStat(
        last_completed_scan_at=last_completed_scan_at,
        last_scan_at=last_scan_at,
    )
    score = EngineScoreStat(
        avg_score=avg_score,
        grade=score_to_grade(avg_score) if avg_score is not None else None,
        scored_targets=score_count,
        by_grade=_grade_stats(grade_counts),
    )
    return coverage, freshness, score


def _max_dt(current: datetime | None, candidate: datetime | None) -> datetime | None:
    if candidate is None:
        return current
    if current is None:
        return candidate
    return max(current, candidate)


def _grade_stats(counts: dict[str, int]) -> list[GradeStat]:
    """Zero-fill the ladder, then append anything the ladder doesn't know.

    Grades are free-form ``VARCHAR(8)``: a scan written before a ladder change
    can hold a value not on it. Appending rather than dropping keeps the
    distribution summing to ``scored_targets``.
    """
    stats = [GradeStat(grade=g, count=counts.get(g, 0)) for g in GRADE_LADDER]
    stats.extend(
        GradeStat(grade=grade, count=count)
        for grade, count in sorted(counts.items())
        if grade not in GRADE_LADDER
    )
    return stats


def _findings(
    session: Session, spec: _OverviewEngine, org_ids: set[uuid.UUID] | None
) -> EngineFindingStat:
    """Open/resolved counts, split by severity and category in one query.

    ``open`` is ``resolved_at IS NULL`` over non-ignored rows — the framing
    ``get_issue_stats`` uses, and the reason CI needs no special case here:
    ``Issue.status`` is owned by a Postgres trigger and is never read.
    """
    finding = spec.finding_model
    is_open = col(finding.resolved_at).is_(None)
    is_critical = finding.severity == IssueSeverity.critical

    query = (
        select(  # type: ignore[call-overload]
            finding.severity,
            finding.category,
            func.sum(case((is_open, 1), else_=0)).label("open"),
            func.sum(case((~is_open, 1), else_=0)).label("resolved"),
            func.sum(case((is_open & is_critical, 1), else_=0)).label("critical_open"),
        )
        .where(col(finding.ignored_at).is_(None))
        .where(_latest_only_predicate(spec))
        .group_by(finding.severity, finding.category)
    )
    if org_ids is not None:
        query = query.where(_finding_org_filter(spec, org_ids))

    by_severity: dict[IssueSeverity, list[int]] = {
        severity: [0, 0] for severity in IssueSeverity
    }
    by_category: dict[IssueCategory, list[int]] = {
        category: [0, 0, 0] for category in IssueCategory
    }
    total_open = total_resolved = total_critical = 0

    for row in session.execute(query).all():
        open_count = row.open or 0
        resolved_count = row.resolved or 0
        critical_count = row.critical_open or 0
        by_severity[row.severity][0] += open_count
        by_severity[row.severity][1] += resolved_count
        by_category[row.category][0] += open_count
        by_category[row.category][1] += resolved_count
        by_category[row.category][2] += critical_count
        total_open += open_count
        total_resolved += resolved_count
        total_critical += critical_count

    return EngineFindingStat(
        open=total_open,
        resolved=total_resolved,
        critical_open=total_critical,
        by_severity=[
            SeverityStat(severity=severity, open=counts[0], resolved=counts[1])
            for severity, counts in by_severity.items()
        ],
        by_category=[
            IssueCategoryStat(
                category=category,
                open=counts[0],
                resolved=counts[1],
                critical_open=counts[2],
            )
            for category, counts in by_category.items()
        ],
    )


def _fix_pipeline(
    session: Session,
    spec: _OverviewEngine,
    org_ids: set[uuid.UUID] | None,
    open_findings: int,
) -> EngineFixPipelineStat | None:
    """Open findings bucketed by the state of the fix addressing them."""
    if spec.fix_model is None:
        return None

    finding = spec.finding_model
    query = (
        select(spec.fix_model.status, func.count(func.distinct(finding.id)))
        .join(spec.fix_model, finding.fix_id == spec.fix_model.id)
        .where(col(finding.resolved_at).is_(None))
        .where(col(finding.ignored_at).is_(None))
        .where(_latest_only_predicate(spec))
        .group_by(spec.fix_model.status)
    )
    if org_ids is not None:
        query = query.where(_finding_org_filter(spec, org_ids))

    counts: dict[FixStatus, int] = defaultdict(int)
    for status, count in session.execute(query).all():
        counts[status] += count

    # Bucket names come from the fix state machine's own status sets rather
    # than a second enumeration of FixStatus here.
    in_progress = sum(counts[status] for status in IN_FLIGHT_STATUSES)
    ready = counts[FixStatus.ready]
    delivered = counts[FixStatus.delivered]
    landed = counts[FixStatus.landed]
    failed = counts[FixStatus.failed]
    # Everything else — no fix row at all, or one in a rejected/superseded
    # state — is unfixed, matching list_issues(unfixed=True). Computing it as
    # the remainder is what keeps the buckets summing to `open`.
    unfixed = max(
        open_findings - (in_progress + ready + delivered + landed + failed), 0
    )

    return EngineFixPipelineStat(
        unfixed=unfixed,
        in_progress=in_progress,
        ready=ready,
        delivered=delivered,
        landed=landed,
        failed=failed,
    )


def _top_rules(
    session: Session,
    spec: _OverviewEngine,
    org_ids: set[uuid.UUID] | None,
    limit: int,
) -> list[TopRuleStat]:
    """The rules accounting for the most open findings on this engine.

    No ``Rule.domain`` filter: the engine's own finding table already
    discriminates exactly, and a Docker target legitimately holds findings from
    both ``container_docker`` and ``container_runtime`` rules — filtering on
    domain would silently drop half of them.
    """
    if limit <= 0:
        return []

    finding = spec.finding_model
    query = (
        select(  # type: ignore[call-overload]
            Rule.id,
            Rule.slug,
            Rule.title,
            Rule.severity,
            Rule.category,
            func.count(finding.id).label("open"),
        )
        .join(Rule, finding.rule_id == Rule.id)
        .where(col(finding.resolved_at).is_(None))
        .where(col(finding.ignored_at).is_(None))
        .where(_latest_only_predicate(spec))
        .group_by(Rule.id, Rule.slug, Rule.title, Rule.severity, Rule.category)
        # slug tiebreak so equal counts order deterministically.
        .order_by(func.count(finding.id).desc(), Rule.slug)
        .limit(limit)
    )
    if org_ids is not None:
        query = query.where(_finding_org_filter(spec, org_ids))

    return [
        TopRuleStat(
            rule_id=row.id,
            slug=row.slug,
            title=row.title,
            severity=row.severity,
            category=row.category,
            open=row.open or 0,
        )
        for row in session.execute(query).all()
    ]


def _totals(engines: list[EngineOverview]) -> OverviewTotals:
    """All-engine roll-up. Pure Python fold — no extra SQL."""
    by_severity: dict[IssueSeverity, list[int]] = {
        severity: [0, 0] for severity in IssueSeverity
    }
    by_category: dict[IssueCategory, list[int]] = {
        category: [0, 0, 0] for category in IssueCategory
    }
    for engine in engines:
        for stat in engine.findings.by_severity:
            by_severity[stat.severity][0] += stat.open
            by_severity[stat.severity][1] += stat.resolved
        for cat_stat in engine.findings.by_category:
            by_category[cat_stat.category][0] += cat_stat.open
            by_category[cat_stat.category][1] += cat_stat.resolved
            by_category[cat_stat.category][2] += cat_stat.critical_open

    engine_scores = [
        engine.score.avg_score
        for engine in engines
        if engine.score.avg_score is not None
    ]
    avg_score = (
        round(sum(engine_scores) / len(engine_scores), 1) if engine_scores else None
    )

    return OverviewTotals(
        targets=sum(e.coverage.total for e in engines),
        enabled_targets=sum(e.coverage.enabled for e in engines),
        never_scanned_targets=sum(e.coverage.never_scanned for e in engines),
        open_findings=sum(e.findings.open for e in engines),
        resolved_findings=sum(e.findings.resolved for e in engines),
        critical_open=sum(e.findings.critical_open for e in engines),
        avg_score=avg_score,
        grade=score_to_grade(avg_score) if avg_score is not None else None,
        by_severity=[
            SeverityStat(severity=severity, open=counts[0], resolved=counts[1])
            for severity, counts in by_severity.items()
        ],
        by_category=[
            IssueCategoryStat(
                category=category,
                open=counts[0],
                resolved=counts[1],
                critical_open=counts[2],
            )
            for category, counts in by_category.items()
        ],
        engines_with_data=sum(1 for e in engines if e.coverage.total > 0),
    )


# ─── Route ────────────────────────────────────────────────────────────────────


@router.get("/", response_model=OverviewPublic)
def get_overview(
    session: SessionDep,
    current_user: CurrentUser,
    org_id: uuid.UUID | None = None,
    top_rules_limit: int = Query(default=5, ge=0, le=20),
) -> OverviewPublic:
    """Aggregated stats for every analysis engine, for the dashboard.

    Always returns all four engines, zeroed where there is nothing to report,
    so the dashboard renders a stable set of sections rather than appearing to
    lose one when an org has no Terraform roots yet.

    Scoping mirrors the other org-wide readers: an explicit ``org_id`` is
    authorized and used alone; otherwise a superuser sees everything and every
    other user sees the orgs they belong to.
    """
    if org_id is not None:
        authorize_org(session, current_user, org_id)
        org_ids: set[uuid.UUID] | None = {org_id}
    elif current_user.is_superuser:
        org_ids = None
    else:
        org_ids = user_org_ids(session, current_user)

    engines: list[EngineOverview] = []
    for spec in _engine_specs():
        coverage, freshness, score = _coverage_and_score(session, spec, org_ids)
        findings = _findings(session, spec, org_ids)
        engines.append(
            EngineOverview(
                engine=spec.key,
                section=spec.section,
                label=spec.label,
                coverage=coverage,
                freshness=freshness,
                score=score,
                findings=findings,
                fixes=_fix_pipeline(session, spec, org_ids, findings.open),
                top_rules=_top_rules(session, spec, org_ids, top_rules_limit),
            )
        )

    return OverviewPublic(
        generated_at=datetime.now(timezone.utc),
        totals=_totals(engines),
        engines=engines,
    )
