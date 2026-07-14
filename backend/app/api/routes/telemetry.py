import json
import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlmodel import select

from app.api.deps import GitHubOidcClaims, SessionDep
from app.models import (
    DynamicAnalysisStatus,
    Repository,
    TelemetryMetricSample,
    TelemetryPhase,
    TelemetryRun,
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
    )

    try:
        session.add(sample)
        session.commit()
    except Exception:
        logger.exception("Failed to persist telemetry sample for repo %s", repository)
        session.rollback()

    return {"status": "ok"}
