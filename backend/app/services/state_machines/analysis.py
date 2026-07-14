"""Analysis lifecycle state machine (``python-statemachine``).

States mirror ``AnalysisStatus``. The graph is connected and single-initial (a
library requirement), which also closes the old gaps: the never-persisted
``pending`` and ``skipped`` values are absent, and ``no_workflows`` is reached
by an explicit ``no_workflows_found`` edge instead of being a disconnected
initial state.

Behaviour lives in ``workers/tasks/static_analysis.py`` and ``maintenance.py``.
"""

from __future__ import annotations

from statemachine import State, StateMachine

from app.models.enums import AnalysisStatus, SSESignal


class AnalysisMachine(StateMachine):
    state_field = "status"

    queued = State(initial=True, value=AnalysisStatus.queued)
    running = State(value=AnalysisStatus.running)
    completed = State(value=AnalysisStatus.completed, final=True)
    # Not ``final``: ``retry`` re-queues a (transient) failure in place. Whether
    # a retry is worthwhile is carried by ``Analysis.failure_kind``.
    failed = State(value=AnalysisStatus.failed)
    no_workflows = State(value=AnalysisStatus.no_workflows, final=True)

    # Inputs (events)
    started = queued.to(running)  # worker begins OPA evaluation
    opa_succeeded = running.to(completed)
    opa_failed = running.to(failed)
    no_workflows_found = running.to(no_workflows)
    # maintenance sweeper; a task may die while still ``queued`` (worker/broker
    # down) or mid-eval in ``running`` — both are swept to ``failed``.
    swept = queued.to(failed) | running.to(failed)
    # In-place recovery for a failed analysis: re-queue the same row so the
    # worker re-runs it (mirrors ``Fix.regenerate``).
    retry = failed.to(queued)

    # Outputs (SSE signal emitted when each event fires)
    outputs: dict[str, SSESignal | None] = {
        "started": SSESignal.analysis_started,
        "opa_succeeded": SSESignal.analysis_completed,
        "opa_failed": SSESignal.analysis_failed,
        "no_workflows_found": SSESignal.analysis_no_workflows,
        "swept": SSESignal.analysis_failed,
        "retry": SSESignal.analysis_queued,
    }
