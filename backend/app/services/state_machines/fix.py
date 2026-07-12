"""Fix lifecycle state machine (``python-statemachine``).

States mirror ``FixStatus``. Behaviour lives in ``fix_generation.py``,
``fix_delivery.py``, ``api/routes/fixes.py`` and ``maintenance.py``.
"""

from __future__ import annotations

from statemachine import State, StateMachine

from app.models.enums import FixStatus, SSESignal

# Statuses a worker is actively processing — a fix here may not be regenerated
# out from under the worker. Single source of truth for fixes.IN_FLIGHT_STATUSES.
IN_FLIGHT_STATUSES: frozenset[FixStatus] = frozenset(
    {FixStatus.pending, FixStatus.generating, FixStatus.delivering}
)


class FixMachine(StateMachine):
    state_field = "status"

    pending = State(initial=True, value=FixStatus.pending)
    generating = State(value=FixStatus.generating)
    ready = State(value=FixStatus.ready)
    delivering = State(value=FixStatus.delivering)
    delivered = State(value=FixStatus.delivered)
    failed = State(value=FixStatus.failed, final=True)
    rejected = State(value=FixStatus.rejected)

    # Inputs (events)
    start_generation = pending.to(generating)
    generation_succeeded = generating.to(ready)
    generation_failed = generating.to(failed)
    mark_ready = ready.to.itself() | delivered.to(ready)  # type: ignore[no-untyped-call]
    start_delivery = ready.to(delivering)
    precheck_failed = ready.to(failed)
    delivery_succeeded = delivering.to(delivered)
    delivery_failed = delivering.to(failed)
    supersede_closed_pr = ready.to(rejected)
    # User reject is legal from every non-in-flight state; the self-loop keeps a
    # repeated DELETE idempotent.
    reject = (
        pending.to(rejected)
        | generating.to(rejected)
        | ready.to(rejected)
        | delivering.to(rejected)
        | delivered.to(rejected)
        | rejected.to.itself()  # type: ignore[no-untyped-call]
    )
    restore = rejected.to(ready)
    swept = pending.to(failed) | generating.to(failed) | delivering.to(failed)

    # Outputs (SSE signal emitted when each event fires)
    outputs: dict[str, SSESignal | None] = {
        "start_generation": SSESignal.fix_generating,
        "generation_succeeded": SSESignal.fix_ready,
        "generation_failed": SSESignal.fix_failed,
        "mark_ready": None,
        "start_delivery": SSESignal.fix_delivering,
        "precheck_failed": SSESignal.fix_failed,
        "delivery_succeeded": SSESignal.fix_delivered,
        "delivery_failed": SSESignal.fix_failed,
        "supersede_closed_pr": SSESignal.fix_rejected,
        "reject": SSESignal.fix_rejected,
        "restore": None,
        "swept": SSESignal.fix_failed,
    }
