"""Fix lifecycle state machine.

Mirrors ``FixStatus`` and the behaviour in ``fix_generation.py``,
``fix_delivery.py``, ``api/routes/fixes.py`` and ``maintenance.py``.

Known gaps (see ``docs/state-machines.md``), preserved here as-is:

* ``rejected`` is overloaded — it covers both a user rejection (``reject``)
  and the automatic closed-PR guard (``supersede_closed_pr``). The two are
  distinguished downstream only by ``delivered_at`` being ``NULL``.
* Regeneration deletes the row rather than transitioning it, so there is no
  edge out of a terminal state back to ``pending``; a fresh ``pending`` fix is
  created instead.
"""

from __future__ import annotations

import enum

from app.models.enums import FixStatus, SSESignal

from .base import StateMachine, Transition

# Statuses a worker is actively processing — a fix here may not be regenerated
# out from under the worker. Mirrors fixes.IN_FLIGHT_STATUSES.
IN_FLIGHT_STATUSES: frozenset[FixStatus] = frozenset(
    {FixStatus.pending, FixStatus.generating, FixStatus.delivering}
)


class FixEvent(str, enum.Enum):
    """Inputs that drive a fix between states."""

    start_generation = "start_generation"  # worker begins the LLM call
    generation_succeeded = "generation_succeeded"  # valid workflow YAML produced
    generation_failed = "generation_failed"  # LLM error / invalid / empty
    mark_ready = "mark_ready"  # unchanged file re-included in a delivery
    start_delivery = "start_delivery"  # delivery batch begins
    precheck_failed = "precheck_failed"  # fix had no content to deliver
    delivery_succeeded = "delivery_succeeded"  # PR opened / updated
    delivery_failed = "delivery_failed"  # GitHub push / PR error
    supersede_closed_pr = "supersede_closed_pr"  # closed-PR guard auto-rejects
    reject = "reject"  # user rejects the fix
    restore = "restore"  # PR reopened; guard-rejected fix becomes deliverable
    swept = "swept"  # maintenance sweeper declared it stuck


# Every state a user may reject from. The DELETE route sets ``rejected``
# regardless of current status; ``rejected`` itself is included so a repeated
# reject is an idempotent no-op rather than an error.
_REJECTABLE = frozenset(
    {
        FixStatus.pending,
        FixStatus.generating,
        FixStatus.ready,
        FixStatus.delivering,
        FixStatus.delivered,
        FixStatus.failed,
        FixStatus.rejected,
    }
)


_transitions: tuple[Transition[FixStatus, FixEvent], ...] = (
    Transition(
        event=FixEvent.start_generation,
        sources=frozenset({FixStatus.pending}),
        dest=FixStatus.generating,
        output=SSESignal.fix_generating,
        description="Worker picked up the pending fix and started the LLM call.",
    ),
    Transition(
        event=FixEvent.generation_succeeded,
        sources=frozenset({FixStatus.generating}),
        dest=FixStatus.ready,
        output=SSESignal.fix_ready,
        guard="LLM output is valid workflow YAML",
        description="Regenerated workflow content accepted.",
    ),
    Transition(
        event=FixEvent.generation_failed,
        sources=frozenset({FixStatus.generating}),
        dest=FixStatus.failed,
        output=SSESignal.fix_failed,
        description="LLM raised, or returned empty / invalid YAML.",
    ),
    Transition(
        event=FixEvent.mark_ready,
        sources=frozenset({FixStatus.ready, FixStatus.delivered}),
        dest=FixStatus.ready,
        description="Unchanged file's fix re-included so it rides along on the "
        "next hard-reset PR delivery.",
    ),
    Transition(
        event=FixEvent.start_delivery,
        sources=frozenset({FixStatus.ready}),
        dest=FixStatus.delivering,
        output=SSESignal.fix_delivering,
        description="Delivery batch began pushing this fix.",
    ),
    Transition(
        event=FixEvent.precheck_failed,
        sources=frozenset({FixStatus.ready}),
        dest=FixStatus.failed,
        output=SSESignal.fix_failed,
        description="Fix reached delivery with no generated content.",
    ),
    Transition(
        event=FixEvent.delivery_succeeded,
        sources=frozenset({FixStatus.delivering}),
        dest=FixStatus.delivered,
        output=SSESignal.fix_delivered,
        description="PR opened or updated with this fix.",
    ),
    Transition(
        event=FixEvent.delivery_failed,
        sources=frozenset({FixStatus.delivering}),
        dest=FixStatus.failed,
        output=SSESignal.fix_failed,
        description="GitHub push or PR creation failed (stale content also "
        "re-queues an analysis).",
    ),
    Transition(
        event=FixEvent.supersede_closed_pr,
        sources=frozenset({FixStatus.ready}),
        dest=FixStatus.rejected,
        output=SSESignal.fix_rejected,
        guard="target PR branch is closed and delivery is not forced",
        description="Closed-PR guard auto-rejected the fix (delivered_at stays "
        "NULL to mark it guard-rejected).",
    ),
    Transition(
        event=FixEvent.reject,
        sources=_REJECTABLE,
        dest=FixStatus.rejected,
        output=SSESignal.fix_rejected,
        description="User rejected the fix via the API.",
    ),
    Transition(
        event=FixEvent.restore,
        sources=frozenset({FixStatus.rejected}),
        dest=FixStatus.ready,
        guard="guard-rejected only (delivered_at is NULL)",
        description="PR reopened; a guard-rejected fix becomes deliverable again.",
    ),
    Transition(
        event=FixEvent.swept,
        sources=IN_FLIGHT_STATUSES,
        dest=FixStatus.failed,
        output=SSESignal.fix_failed,
        guard="created_at older than STUCK_AFTER_MINUTES",
        description="Maintenance sweeper failed a fix stuck in a transient "
        "state after a worker crash.",
    ),
)

fix_machine: StateMachine[FixStatus, FixEvent] = StateMachine(
    name="fix",
    state_attr="status",
    state_enum=FixStatus,
    event_enum=FixEvent,
    transitions=_transitions,
    initial_states=frozenset({FixStatus.pending}),
    terminal_states=frozenset(
        {FixStatus.delivered, FixStatus.failed, FixStatus.rejected}
    ),
)
