import json
import logging
import uuid

from sqlmodel import Session, col, delete, select

from app.core.db import engine
from app.models import (
    Analysis,
    AnalysisStatus,
    DynamicEnrichment,
    Repository,
    TelemetryRun,
)
from app.services import state_machines as sm
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_dynamic_analysis_impl(telemetry_run_id: str) -> dict[str, str | float]:
    with Session(engine) as session:
        run = session.get(TelemetryRun, uuid.UUID(telemetry_run_id))
        if not run:
            return {"status": "error", "detail": "telemetry_run_not_found"}

        # queued -> running; try_advance tolerates a redelivered/reordered run.
        if sm.try_advance(run, sm.TelemetryMachine, "started"):
            session.add(run)
            session.commit()
            _emit(session, run, "started")

        try:
            enrichment_count = _enrich(session, run)
        except Exception as exc:
            logger.exception(
                "Dynamic analysis failed for telemetry run %s: %s",
                telemetry_run_id,
                exc,
            )
            sm.try_advance(run, sm.TelemetryMachine, "fail")
            session.add(run)
            session.commit()
            _emit(session, run, "fail")
            return {"status": "failed", "telemetry_run_id": telemetry_run_id}

        sm.try_advance(run, sm.TelemetryMachine, "enrich")
        session.add(run)
        session.commit()
        _emit(session, run, "enrich")

        logger.info("Dynamic analysis complete for telemetry run %s", telemetry_run_id)
        return {
            "status": "completed",
            "telemetry_run_id": telemetry_run_id,
            "enrichments": enrichment_count,
        }


def _emit(session: Session, run: TelemetryRun, event: str) -> None:
    """Publish the SSE signal declared as the TelemetryMachine event's output."""
    signal = sm.output_for(sm.TelemetryMachine, event)
    if signal is None:
        return
    repo = session.get(Repository, run.repo_id)
    if repo is None:
        return
    events_pub.publish_event(
        ev.dynamic_status(str(repo.org_id), str(repo.id), str(run.id), signal)
    )


def _enrich(session: Session, run: TelemetryRun) -> int:
    """Compute and persist this run's enrichments; return how many were written."""
    metrics = json.loads(run.metrics or "{}")
    specs = json.loads(run.runner_specs or "{}")

    enrichments: list[dict[str, str | float]] = []

    vcpus = specs.get("vcpus", 0)
    cpu_percent = metrics.get("cpu_percent", 100.0)
    ram_percent = metrics.get("ram_percent", 100.0)

    if vcpus >= 8 and cpu_percent < 25.0 and ram_percent < 30.0:
        enrichments.append(
            {
                "rule_slug": "runner_sizing",
                "evidence": f"vCPUs={vcpus}, CPU={cpu_percent:.1f}%, RAM={ram_percent:.1f}%",
                "recommendation": f"Consider downsizing from {vcpus} vCPUs — actual usage is low",
            }
        )

    latest_analysis = session.exec(
        select(Analysis)
        .where(Analysis.repo_id == run.repo_id)
        .where(Analysis.status == AnalysisStatus.completed)
        .order_by(col(Analysis.created_at).desc())
    ).first()

    # Persist this run's enrichments, replacing any from a prior run of the
    # same telemetry row so re-runs stay idempotent.
    session.exec(
        delete(DynamicEnrichment).where(
            col(DynamicEnrichment.telemetry_run_id) == run.id
        )
    )
    analysis_id = latest_analysis.id if latest_analysis else None
    for enrichment in enrichments:
        session.add(
            DynamicEnrichment(
                repo_id=run.repo_id,
                telemetry_run_id=run.id,
                analysis_id=analysis_id,
                rule_slug=str(enrichment["rule_slug"]),
                evidence=str(enrichment["evidence"]),
                recommendation=str(enrichment["recommendation"]),
            )
        )
    session.commit()

    if enrichments:
        logger.info(
            "Dynamic enrichment for analysis %s: %d signal(s) persisted",
            analysis_id,
            len(enrichments),
        )
    return len(enrichments)


@celery_app.task(name="dynamic_analysis.run", bind=True, max_retries=3)
def run_dynamic_analysis(self: object, telemetry_run_id: str) -> dict[str, str | float]:  # noqa: ARG001
    return _run_dynamic_analysis_impl(telemetry_run_id)
