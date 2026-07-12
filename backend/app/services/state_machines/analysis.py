"""Analysis lifecycle state machine.

Mirrors ``AnalysisStatus`` and the behaviour in
``app/workers/tasks/static_analysis.py`` / ``maintenance.py``.

Known gaps (see ``docs/state-machines.md``), preserved here as-is:

* ``pending`` is never persisted — the worker inserts the row directly as
  ``running`` or ``no_workflows``; the queued phase is SSE-only. It is kept as
  a declared initial state and a legal source for the stuck sweeper.
* ``skipped`` is never persisted — a content-hash duplicate references the
  prior analysis instead of writing a row. It is declared as a terminal state
  for completeness but has no inbound transition.
"""

from __future__ import annotations

import enum

from app.models.enums import AnalysisStatus, SSESignal

from .base import StateMachine, Transition


class AnalysisEvent(str, enum.Enum):
    """Inputs that drive an analysis row between states."""

    opa_succeeded = "opa_succeeded"  # OPA evaluation produced a score
    opa_failed = "opa_failed"  # OPA evaluation raised
    swept = "swept"  # maintenance sweeper declared it stuck


_transitions: tuple[Transition[AnalysisStatus, AnalysisEvent], ...] = (
    Transition(
        event=AnalysisEvent.opa_succeeded,
        sources=frozenset({AnalysisStatus.running}),
        dest=AnalysisStatus.completed,
        output=SSESignal.analysis_completed,
        description="OPA evaluation finished; score and grade recorded.",
    ),
    Transition(
        event=AnalysisEvent.opa_failed,
        sources=frozenset({AnalysisStatus.running}),
        dest=AnalysisStatus.failed,
        output=SSESignal.analysis_failed,
        description="OPA evaluation raised for this workflow file.",
    ),
    Transition(
        event=AnalysisEvent.swept,
        sources=frozenset({AnalysisStatus.pending, AnalysisStatus.running}),
        dest=AnalysisStatus.failed,
        output=SSESignal.analysis_failed,
        guard="created_at older than STUCK_AFTER_MINUTES",
        description="Maintenance sweeper failed an analysis stuck in a "
        "transient state after a worker crash.",
    ),
)

analysis_machine: StateMachine[AnalysisStatus, AnalysisEvent] = StateMachine(
    name="analysis",
    state_attr="status",
    state_enum=AnalysisStatus,
    event_enum=AnalysisEvent,
    transitions=_transitions,
    # Rows are created directly as ``running`` or ``no_workflows``; ``pending``
    # is declared but never persisted (see module docstring).
    initial_states=frozenset(
        {
            AnalysisStatus.pending,
            AnalysisStatus.running,
            AnalysisStatus.no_workflows,
        }
    ),
    # ``skipped`` is intentionally absent: a duplicate references the prior
    # analysis rather than writing a row, so the machine never reaches it (see
    # module docstring). It remains a valid ``AnalysisStatus`` value.
    terminal_states=frozenset(
        {
            AnalysisStatus.completed,
            AnalysisStatus.failed,
            AnalysisStatus.no_workflows,
        }
    ),
)
