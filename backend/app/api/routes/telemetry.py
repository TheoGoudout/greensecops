import json
import logging
from typing import Any

from fastapi import APIRouter, Header
from pydantic import BaseModel
from sqlmodel import select

from app.api.deps import SessionDep
from app.models import Repository, TelemetryRun

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


class TelemetryPayload(BaseModel):
    workflow_run_id: int
    repository: str  # "owner/repo"
    branch: str = ""
    commit_sha: str = ""
    workflow_name: str = ""
    runner_specs: dict[str, Any] = {}
    metrics: dict[str, Any] = {}


@router.post("/ingest", status_code=201)
async def ingest_telemetry(
    payload: TelemetryPayload,
    session: SessionDep,
    authorization: str | None = Header(default=None),  # noqa: ARG001
) -> dict[str, str]:
    # Find repository by full_name
    repo = session.exec(
        select(Repository).where(Repository.full_name == payload.repository)
    ).first()

    if not repo:
        # Accept telemetry from unknown repos silently (repo not yet installed)
        logger.info(
            "Telemetry received for unregistered repo %s — ignoring",
            payload.repository,
        )
        return {"status": "accepted", "note": "repository_not_registered"}

    # Check for duplicate run
    existing = session.exec(
        select(TelemetryRun)
        .where(TelemetryRun.repo_id == repo.id)
        .where(TelemetryRun.workflow_run_id == payload.workflow_run_id)
    ).first()
    if existing:
        return {"status": "accepted", "note": "duplicate_run"}

    run = TelemetryRun(
        repo_id=repo.id,
        workflow_run_id=payload.workflow_run_id,
        runner_specs=json.dumps(payload.runner_specs),
        metrics=json.dumps(payload.metrics),
    )
    session.add(run)
    session.commit()

    logger.info(
        "Telemetry ingested: repo=%s run_id=%d",
        payload.repository,
        payload.workflow_run_id,
    )
    return {"status": "accepted", "telemetry_run_id": str(run.id)}
