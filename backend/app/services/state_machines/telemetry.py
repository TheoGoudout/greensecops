"""Dynamic-analysis (telemetry enrichment) state machine.

States mirror ``DynamicAnalysisStatus`` and track the worker that turns a
``completed``-phase :class:`TelemetryRun`'s metrics into persisted
:class:`DynamicEnrichment` findings. This is distinct from ``TelemetryPhase``,
which is an ingest *category* (``started`` and ``completed`` are separate rows),
not a per-row progression.

Only ``completed``-phase rows enter this machine (their ``dynamic_status`` is set
to ``queued`` at ingest); ``started``-phase rows leave ``dynamic_status`` NULL.
Behaviour lives in ``api/routes/telemetry.py`` and
``workers/tasks/dynamic_analysis.py``.
"""

from __future__ import annotations

from statemachine import State, StateMachine

from app.models.enums import DynamicAnalysisStatus, SSESignal


class TelemetryMachine(StateMachine):
    state_field = "dynamic_status"

    queued = State(initial=True, value=DynamicAnalysisStatus.queued)
    running = State(value=DynamicAnalysisStatus.running)
    enriched = State(value=DynamicAnalysisStatus.enriched, final=True)
    # Not ``final``: ``retry`` re-queues a failed enrichment in place.
    failed = State(value=DynamicAnalysisStatus.failed)

    # Inputs (events)
    started = queued.to(running)  # worker begins enrichment
    enrich = running.to(enriched)  # enrichments persisted
    fail = running.to(failed)  # worker raised
    retry = failed.to(queued)  # re-queue a failed run
    # Stuck-row sweeper (mirrors ScanMachine.swept): a row that never got
    # picked up (``queued``) or whose worker died mid-enrichment (``running``)
    # is declared failed after the shared staleness cutoff.
    swept = queued.to(failed) | running.to(failed)

    # Outputs (SSE signal emitted when each event fires)
    outputs: dict[str, SSESignal | None] = {
        "started": SSESignal.dynamic_running,
        "enrich": SSESignal.dynamic_enriched,
        "fail": SSESignal.dynamic_failed,
        "retry": SSESignal.dynamic_queued,
        "swept": SSESignal.dynamic_failed,
    }
