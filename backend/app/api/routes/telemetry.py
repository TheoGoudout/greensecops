import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import col, select

from app.api.deps import (
    CurrentUser,
    GitHubOidcClaims,
    SessionDep,
    authorize_repo,
)
from app.api.mappers import (
    compute_telemetry_average,
    to_dynamic_enrichment_public,
    to_telemetry_run_public,
)
from app.models import (
    DynamicAnalysisStatus,
    DynamicEnrichment,
    DynamicEnrichmentPublic,
    Repository,
    TelemetryMetricSample,
    TelemetryPhase,
    TelemetryRun,
    TelemetrySummaryPublic,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


class TelemetryPayload(BaseModel):
    workflow_run_id: int
    branch: str = ""
    commit_sha: str = ""
    workflow_name: str = ""
    runner_specs: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    phase: TelemetryPhase = TelemetryPhase.completed


class SamplePayload(BaseModel):
    workflow_run_id: int
    cpu_percent: float | None = None
    ram_used_mb: float | None = None
    disk_used_gb: float | None = None
    net_bytes_sent: int | None = None
    net_bytes_recv: int | None = None
    # Top 5-10% resource-consuming processes from the proc-sampler binary
    # (Linux runners only); absent elsewhere or if sampling failed.
    top_processes: list[dict[str, Any]] | None = None


def _lookup_repo(session: SessionDep, repository: str) -> Repository | None:
    return session.exec(
        select(Repository).where(Repository.full_name == repository)
    ).first()


@router.post("/ingest", status_code=201)
async def ingest_telemetry(
    payload: TelemetryPayload,
    session: SessionDep,
    claims: GitHubOidcClaims,
) -> dict[str, str]:
    repository: str = claims.get("repository", "")

    repo = _lookup_repo(session, repository)
    if not repo:
        logger.info(
            "Telemetry received for unregistered repo %s — ignoring",
            repository,
        )
        return {"status": "accepted", "note": "repository_not_registered"}

    existing = session.exec(
        select(TelemetryRun)
        .where(TelemetryRun.repo_id == repo.id)
        .where(TelemetryRun.workflow_run_id == payload.workflow_run_id)
        .where(TelemetryRun.phase == payload.phase)
    ).first()

    if existing:
        return {"status": "accepted", "note": "duplicate_run_phase"}

    run = TelemetryRun(
        repo_id=repo.id,
        workflow_run_id=payload.workflow_run_id,
        runner_specs=json.dumps(payload.runner_specs),
        metrics=json.dumps(payload.metrics),
        phase=payload.phase,
        # Only completed-phase rows enrich; mark them queued so the worker can
        # advance them through the TelemetryMachine.
        dynamic_status=(
            DynamicAnalysisStatus.queued
            if payload.phase == TelemetryPhase.completed
            else None
        ),
    )
    session.add(run)
    session.commit()

    # A completed run carries the full metrics needed for enrichment; queue the
    # dynamic analysis that turns them into persisted findings.
    if payload.phase == TelemetryPhase.completed:
        from app.workers.tasks.dynamic_analysis import run_dynamic_analysis

        run_dynamic_analysis.delay(str(run.id))

    logger.info(
        "Telemetry ingested: repo=%s run_id=%d phase=%s",
        repository,
        payload.workflow_run_id,
        payload.phase,
    )
    return {"status": "accepted", "telemetry_run_id": str(run.id)}


@router.post("/sample", status_code=200)
async def ingest_sample(
    payload: SamplePayload,
    session: SessionDep,
    claims: GitHubOidcClaims,
) -> dict[str, str]:
    repository: str = claims.get("repository", "")

    repo = _lookup_repo(session, repository)
    if not repo:
        return {"status": "ok"}

    sample = TelemetryMetricSample(
        repo_id=repo.id,
        workflow_run_id=payload.workflow_run_id,
        cpu_percent=payload.cpu_percent,
        ram_used_mb=payload.ram_used_mb,
        disk_used_gb=payload.disk_used_gb,
        net_bytes_sent=payload.net_bytes_sent,
        net_bytes_recv=payload.net_bytes_recv,
        top_processes=(
            json.dumps(payload.top_processes) if payload.top_processes else None
        ),
    )

    try:
        session.add(sample)
        session.commit()
    except Exception:
        logger.exception("Failed to persist telemetry sample for repo %s", repository)
        session.rollback()

    return {"status": "ok"}


# ─── Read / analyze (user-session authenticated) ──────────────────────────────


def _enrichments_by_run(
    session: SessionDep, repo_id: uuid.UUID
) -> dict[uuid.UUID, list[DynamicEnrichment]]:
    """Group a repo's dynamic-enrichment findings by their telemetry run."""
    grouped: dict[uuid.UUID, list[DynamicEnrichment]] = {}
    rows = session.exec(
        select(DynamicEnrichment)
        .where(DynamicEnrichment.repo_id == repo_id)
        .order_by(col(DynamicEnrichment.created_at).desc())
    ).all()
    for row in rows:
        grouped.setdefault(row.telemetry_run_id, []).append(row)
    return grouped


@router.get("/summary/{repo_id}", response_model=TelemetrySummaryPublic)
def get_telemetry_summary(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    limit: int = 50,
    skip: int = 0,
) -> TelemetrySummaryPublic:
    """Average telemetry plus a per-run breakdown for a repository.

    Averages are computed over every telemetry run/sample the repo has; the
    ``runs`` list is paginated (most recent first) for the by-run table.
    """
    repo = authorize_repo(session, current_user, repo_id)

    all_runs = session.exec(
        select(TelemetryRun)
        .where(TelemetryRun.repo_id == repo.id)
        .order_by(col(TelemetryRun.collected_at).desc())
    ).all()
    samples = session.exec(
        select(TelemetryMetricSample).where(TelemetryMetricSample.repo_id == repo.id)
    ).all()

    average = compute_telemetry_average(list(all_runs), list(samples))

    enrichments = _enrichments_by_run(session, repo.id)
    paged = all_runs[skip : skip + limit]
    runs = [to_telemetry_run_public(run, enrichments.get(run.id, [])) for run in paged]
    return TelemetrySummaryPublic(average=average, runs=runs)


@router.get("/findings/{repo_id}", response_model=list[DynamicEnrichmentPublic])
def get_telemetry_findings(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[DynamicEnrichmentPublic]:
    """A repo's runtime findings, for the Issues-page "Runtime" section."""
    repo = authorize_repo(session, current_user, repo_id)

    run_ids = {
        run.id: run.workflow_run_id
        for run in session.exec(
            select(TelemetryRun).where(TelemetryRun.repo_id == repo.id)
        ).all()
    }
    findings = session.exec(
        select(DynamicEnrichment)
        .where(DynamicEnrichment.repo_id == repo.id)
        .order_by(col(DynamicEnrichment.created_at).desc())
    ).all()
    return [
        to_dynamic_enrichment_public(f, run_ids.get(f.telemetry_run_id))
        for f in findings
    ]


@router.post("/analyze/{repo_id}", status_code=202)
def analyze_telemetry(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, str | int]:
    """Re-run dynamic analysis over the repo's completed telemetry runs.

    The CI action collects telemetry during workflow runs; this re-derives
    findings from what is already stored. ``_enrich`` replaces a run's prior
    enrichments, so re-running is idempotent.
    """
    repo = authorize_repo(session, current_user, repo_id)
    if not repo.is_accessible:
        raise HTTPException(status_code=403, detail="Repository is not accessible")

    from app.workers.tasks.dynamic_analysis import run_dynamic_analysis

    runs = session.exec(
        select(TelemetryRun)
        .where(TelemetryRun.repo_id == repo.id)
        .where(TelemetryRun.phase == TelemetryPhase.completed)
    ).all()
    for run in runs:
        run.dynamic_status = DynamicAnalysisStatus.queued
        session.add(run)
        run_dynamic_analysis.delay(str(run.id))
    session.commit()

    return {"status": "queued", "runs": len(runs)}
