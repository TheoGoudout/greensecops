import json
import logging
import uuid

from sqlmodel import Session, select

from app.core.db import engine
from app.models import Analysis, AnalysisStatus, TelemetryRun
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="dynamic_analysis.run", bind=True, max_retries=3)
def run_dynamic_analysis(self: object, telemetry_run_id: str) -> dict[str, str | float]:  # noqa: ARG001
    with Session(engine) as session:
        run = session.get(TelemetryRun, uuid.UUID(telemetry_run_id))
        if not run:
            return {"status": "error", "detail": "telemetry_run_not_found"}

        metrics = json.loads(run.metrics or "{}")
        specs = json.loads(run.runner_specs or "{}")

        enrichments: list[dict[str, str | float]] = []

        # Check if runner is oversized based on actual CPU usage
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

        # Find the latest completed analysis for this repo to attach enrichment
        latest_analysis = session.exec(
            select(Analysis)
            .where(Analysis.repo_id == run.repo_id)
            .where(Analysis.status == AnalysisStatus.completed)
            .order_by(Analysis.created_at.desc())  # type: ignore[arg-type]
        ).first()

        if latest_analysis and enrichments:
            logger.info(
                "Dynamic enrichment for analysis %s: %d signals",
                latest_analysis.id,
                len(enrichments),
            )

        logger.info("Dynamic analysis complete for telemetry run %s", telemetry_run_id)
        return {
            "status": "completed",
            "telemetry_run_id": telemetry_run_id,
            "enrichments": len(enrichments),
        }
