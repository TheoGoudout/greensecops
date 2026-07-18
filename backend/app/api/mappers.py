import json
from typing import Any

from app.models import (
    Analysis,
    AnalysisPublic,
    DynamicEnrichment,
    DynamicEnrichmentPublic,
    Issue,
    IssuePublic,
    Repository,
    RepositoryPublic,
    TelemetryAveragePublic,
    TelemetryMetricSample,
    TelemetryRun,
    TelemetryRunPublic,
)


def to_analysis_public(analysis: Analysis) -> AnalysisPublic:
    return AnalysisPublic(
        id=analysis.id,
        repo_id=analysis.repo_id,
        workflow_file_id=analysis.workflow_file_id,
        workflow_file_path=(
            analysis.workflow_file.path if analysis.workflow_file else None
        ),
        repo_full_name=(analysis.repository.full_name if analysis.repository else None),
        content_hash=analysis.content_hash,
        status=analysis.status,
        score=analysis.score,
        grade=analysis.grade,
        triggered_by=analysis.triggered_by,
        branch=analysis.branch,
        commit_sha=analysis.commit_sha,
        created_at=analysis.created_at,
        completed_at=analysis.completed_at,
    )


def to_issue_public(issue: Issue) -> IssuePublic:
    fix = issue.fix
    analysis = issue.analysis
    workflow_file_path = (
        analysis.workflow_file.path if analysis and analysis.workflow_file else None
    )
    return IssuePublic(
        id=issue.id,
        analysis_id=issue.analysis_id,
        rule_id=issue.rule_id,
        rule_slug=issue.rule.slug if issue.rule else "",
        severity=issue.severity,
        category=issue.category,
        line_start=issue.line_start,
        line_end=issue.line_end,
        message=issue.message,
        context=issue.context,
        status=issue.status,
        created_at=issue.created_at,
        resolved_at=issue.resolved_at,
        resolution_reason=issue.resolution_reason,
        fix_id=fix.id if fix else None,
        fix_status=fix.status if fix else None,
        workflow_file_path=workflow_file_path,
    )


def _loads_dict(raw: str | None) -> dict[str, Any]:
    """Parse a stored JSON blob into a dict, tolerating null/invalid data.

    Mirrors the defensive ``json.loads(... or "{}")`` used by the dynamic
    analysis worker so a malformed row never breaks the read path.
    """
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def to_dynamic_enrichment_public(
    enrichment: DynamicEnrichment, workflow_run_id: int | None = None
) -> DynamicEnrichmentPublic:
    return DynamicEnrichmentPublic(
        id=enrichment.id,
        telemetry_run_id=enrichment.telemetry_run_id,
        workflow_run_id=workflow_run_id,
        rule_slug=enrichment.rule_slug,
        evidence=enrichment.evidence,
        recommendation=enrichment.recommendation,
        created_at=enrichment.created_at,
    )


def to_telemetry_run_public(
    run: TelemetryRun, enrichments: list[DynamicEnrichment]
) -> TelemetryRunPublic:
    return TelemetryRunPublic(
        id=run.id,
        workflow_run_id=run.workflow_run_id,
        phase=run.phase,
        dynamic_status=run.dynamic_status,
        runner_specs=_loads_dict(run.runner_specs),
        metrics=_loads_dict(run.metrics),
        collected_at=run.collected_at,
        enrichments=[
            to_dynamic_enrichment_public(e, run.workflow_run_id) for e in enrichments
        ],
    )


def compute_telemetry_average(
    runs: list[TelemetryRun], samples: list[TelemetryMetricSample]
) -> TelemetryAveragePublic:
    """Average telemetry across a repo's runs and time-series samples.

    Sample-derived fields ignore ``None`` gaps (each is averaged over the
    samples that reported it); ``avg_ram_percent``/``avg_vcpus`` come from the
    per-run ``metrics``/``runner_specs`` JSON.
    """

    def _avg(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 2) if values else None

    def _sample_avg(attr: str) -> float | None:
        return _avg([float(v) for s in samples if (v := getattr(s, attr)) is not None])

    ram_percents = [
        float(v)
        for run in runs
        if (v := _loads_dict(run.metrics).get("ram_percent")) is not None
    ]
    vcpus = [
        float(v)
        for run in runs
        if (v := _loads_dict(run.runner_specs).get("vcpus")) is not None
    ]

    return TelemetryAveragePublic(
        run_count=len(runs),
        sample_count=len(samples),
        avg_cpu_percent=_sample_avg("cpu_percent"),
        avg_ram_used_mb=_sample_avg("ram_used_mb"),
        avg_ram_percent=_avg(ram_percents),
        avg_disk_used_gb=_sample_avg("disk_used_gb"),
        avg_net_bytes_sent=_sample_avg("net_bytes_sent"),
        avg_net_bytes_recv=_sample_avg("net_bytes_recv"),
        avg_vcpus=_avg(vcpus),
    )


def to_repo_public(
    repo: Repository, avg_score: float | None, grade: str | None
) -> RepositoryPublic:
    return RepositoryPublic(
        id=repo.id,
        full_name=repo.full_name,
        enabled=repo.enabled,
        is_accessible=repo.is_accessible,
        is_external=repo.is_external,
        default_branch=repo.default_branch,
        auto_fix_enabled=repo.auto_fix_enabled,
        created_at=repo.created_at,
        avg_score=avg_score,
        grade=grade,
    )
