import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, col, select

from app.core.db import engine
from app.models import (
    Analysis,
    AnalysisFailureKind,
    AnalysisStatus,
    DynamicAnalysisStatus,
    Fix,
    FixStatus,
    TelemetryRun,
)
from app.services import state_machines as sm
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# How long an analysis/fix may sit in a transient state before the sweeper
# declares the worker dead and fails it (workers crashing mid-task otherwise
# leave records in `running`/`generating`/`delivering` forever).
STUCK_AFTER_MINUTES = 30


def _sweep_stuck_states_impl() -> dict[str, int]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=STUCK_AFTER_MINUTES)
    swept_analyses = 0
    swept_fixes = 0
    swept_telemetry = 0
    with Session(engine) as session:
        stuck_analyses = session.exec(
            select(Analysis)
            .where(
                col(Analysis.status).in_(
                    [AnalysisStatus.queued, AnalysisStatus.running]
                )
            )
            .where(Analysis.created_at < cutoff)  # type: ignore[operator]
        ).all()
        for analysis in stuck_analyses:
            sm.advance(analysis, sm.AnalysisMachine, "swept")
            analysis.error_message = (
                "Timed out: the analysis worker was interrupted before completion"
            )
            # A sweep is a transient failure (worker/broker interruption) — safe
            # to retry once the pipeline is healthy again.
            analysis.failure_kind = AnalysisFailureKind.transient
            analysis.completed_at = now
            session.add(analysis)
            swept_analyses += 1

        # Fix rows have no updated_at; created_at is a conservative proxy. A
        # genuinely in-flight task commits its final status afterwards and
        # wins the race, so a false sweep self-corrects.
        stuck_fixes = session.exec(
            select(Fix)
            .where(
                col(Fix.status).in_(
                    [FixStatus.pending, FixStatus.generating, FixStatus.delivering]
                )
            )
            .where(Fix.created_at < cutoff)  # type: ignore[operator]
        ).all()
        for fix in stuck_fixes:
            sm.advance(fix, sm.FixMachine, "swept")
            fix.error_message = (
                "Timed out: the fix worker was interrupted before completion"
            )
            session.add(fix)
            swept_fixes += 1

        # TelemetryRun has no created_at/updated_at; collected_at (set at
        # ingest) is the same kind of conservative proxy used for Fix above.
        stuck_telemetry = session.exec(
            select(TelemetryRun)
            .where(
                col(TelemetryRun.dynamic_status).in_(
                    [DynamicAnalysisStatus.queued, DynamicAnalysisStatus.running]
                )
            )
            .where(TelemetryRun.collected_at < cutoff)  # type: ignore[operator]
        ).all()
        for run in stuck_telemetry:
            sm.advance(run, sm.TelemetryMachine, "swept")
            session.add(run)
            swept_telemetry += 1

        if swept_analyses or swept_fixes or swept_telemetry:
            session.commit()
            logger.warning(
                "Swept %d stuck analysis(es), %d stuck fix(es) and %d stuck "
                "telemetry run(s) to failed",
                swept_analyses,
                swept_fixes,
                swept_telemetry,
            )

    return {
        "swept_analyses": swept_analyses,
        "swept_fixes": swept_fixes,
        "swept_telemetry": swept_telemetry,
    }


@celery_app.task(name="maintenance.sweep_stuck_states", bind=True)
def sweep_stuck_states(self: object) -> dict[str, int]:  # noqa: ARG001
    return _sweep_stuck_states_impl()
