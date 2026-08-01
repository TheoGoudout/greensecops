import asyncio
import json
import logging
import uuid
from typing import Any

from sqlmodel import Session, col, delete

from app.core.db import engine
from app.models import DockerBuildEnrichment, DockerBuildTelemetry
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _build_document(
    telemetry: DockerBuildTelemetry, observed_builds: int
) -> dict[str, Any]:
    """Shape one telemetry row into the document the runtime rules evaluate.

    ``observed_builds`` rides in from the ingest call rather than being stored:
    it is a property of the *series* of builds, not of this one, and rules like
    image_layer_cache_ineffective need it to avoid firing on a first build that
    legitimately missed every layer.
    """
    return {
        "build": {
            "image_size_bytes": telemetry.image_size_bytes,
            "context_size_bytes": telemetry.context_size_bytes,
            "build_duration_ms": telemetry.build_duration_ms,
            "cache_hit_ratio": telemetry.cache_hit_ratio,
            "observed_builds": observed_builds,
            "layers": json.loads(telemetry.layers or "[]"),
        },
        "containers": json.loads(telemetry.containers or "[]"),
    }


def _run_docker_telemetry_analysis_impl(
    telemetry_id: str, observed_builds: int = 0
) -> dict[str, str | int]:
    with Session(engine) as session:
        telemetry = session.get(DockerBuildTelemetry, uuid.UUID(telemetry_id))
        if not telemetry:
            return {"status": "error", "detail": "telemetry_not_found"}

        try:
            violations = asyncio.run(
                _evaluate(_build_document(telemetry, observed_builds))
            )
        except Exception as exc:
            logger.exception(
                "Docker telemetry evaluation failed for %s: %s", telemetry_id, exc
            )
            return {"status": "failed", "telemetry_id": telemetry_id}

        # Replace this row's enrichments so a re-run is idempotent — same
        # delete-and-reinsert dynamic_analysis uses.
        session.exec(
            delete(DockerBuildEnrichment).where(
                col(DockerBuildEnrichment.telemetry_id) == telemetry.id
            )
        )
        for violation in violations:
            session.add(
                DockerBuildEnrichment(
                    repo_id=telemetry.repo_id,
                    telemetry_id=telemetry.id,
                    rule_slug=violation.rule_slug,
                    evidence=violation.evidence,
                    recommendation=violation.recommendation,
                )
            )
        session.commit()

        logger.info(
            "Docker telemetry analysis for %s: %d enrichment(s)",
            telemetry_id,
            len(violations),
        )
        return {
            "status": "completed",
            "telemetry_id": telemetry_id,
            "enrichments": len(violations),
        }


@celery_app.task(name="docker_telemetry_analysis.run", bind=True, max_retries=3)
def run_docker_telemetry_analysis(
    self: object,  # noqa: ARG001
    telemetry_id: str,
    observed_builds: int = 0,
) -> dict[str, str | int]:
    return _run_docker_telemetry_analysis_impl(telemetry_id, observed_builds)


async def _evaluate(document: dict[str, Any]) -> Any:
    from app.services.opa.evaluator import evaluate_container_runtime

    return await evaluate_container_runtime(document)
