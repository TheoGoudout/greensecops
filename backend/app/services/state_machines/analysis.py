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

    running = State(initial=True, value=AnalysisStatus.running)
    completed = State(value=AnalysisStatus.completed, final=True)
    failed = State(value=AnalysisStatus.failed, final=True)
    no_workflows = State(value=AnalysisStatus.no_workflows, final=True)

    # Inputs (events)
    opa_succeeded = running.to(completed)
    opa_failed = running.to(failed)
    no_workflows_found = running.to(no_workflows)
    swept = running.to(failed)  # maintenance sweeper; same edge, distinct input

    # Outputs (SSE signal emitted when each event fires)
    outputs: dict[str, SSESignal | None] = {
        "opa_succeeded": SSESignal.analysis_completed,
        "opa_failed": SSESignal.analysis_failed,
        "no_workflows_found": SSESignal.analysis_no_workflows,
        "swept": SSESignal.analysis_failed,
    }
