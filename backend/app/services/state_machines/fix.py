"""Fix lifecycle state machine (``python-statemachine``).

States mirror ``FixStatus``. Behaviour lives in ``fix_generation.py``,
``fix_delivery.py``, ``api/routes/fixes.py`` and ``maintenance.py``.

The two rejection states are distinct (no longer disambiguated by a
``delivered_at IS NULL`` convention):

* ``rejected_by_user`` — a human dismissed the fix; terminal (idempotent
  re-reject only).
* ``superseded_by_closed_pr`` — the closed-PR delivery guard auto-rejected it;
  ``restore`` makes it deliverable again when the PR is reopened.
* ``superseded_by_deleted_file`` — the workflow file the fix targets was
  deleted from the repo; ``restore`` makes it deliverable again if a later
  push re-adds the same path.
"""

from __future__ import annotations

from statemachine import State, StateMachine

from app.models.enums import FixStatus, SSESignal

# Statuses a worker is actively processing — a fix here may not be regenerated
# out from under the worker. Single source of truth for fixes.IN_FLIGHT_STATUSES.
IN_FLIGHT_STATUSES: frozenset[FixStatus] = frozenset(
    {FixStatus.pending, FixStatus.generating, FixStatus.delivering}
)

# The rejection/withdrawal states — an issue whose fix is in any of these is
# not actively being addressed. Single source of truth for the "active fix"
# filter.
REJECTED_STATUSES: frozenset[FixStatus] = frozenset(
    {
        FixStatus.rejected_by_user,
        FixStatus.superseded_by_closed_pr,
        FixStatus.superseded_by_deleted_file,
    }
)


class FixMachine(StateMachine):
    state_field = "status"

    pending = State(initial=True, value=FixStatus.pending)
    generating = State(value=FixStatus.generating)
    ready = State(value=FixStatus.ready)
    delivering = State(value=FixStatus.delivering)
    delivered = State(value=FixStatus.delivered)
    # Not ``final``: ``regenerate`` gives a failed fix a path back to
    # ``pending`` so recovery reuses the row instead of creating a new one.
    failed = State(value=FixStatus.failed)
    rejected_by_user = State(value=FixStatus.rejected_by_user, final=True)
    superseded = State(value=FixStatus.superseded_by_closed_pr)
    superseded_deleted_file = State(value=FixStatus.superseded_by_deleted_file)
    # Terminal success: the fix's PR was merged. Distinct from ``delivered``
    # (awaiting review) so "landed on the branch" is queryable.
    landed = State(value=FixStatus.landed, final=True)

    # Inputs (events)
    start_generation = pending.to(generating)
    generation_succeeded = generating.to(ready)
    generation_failed = generating.to(failed)
    mark_ready = ready.to.itself() | delivered.to(ready)  # type: ignore[no-untyped-call]
    start_delivery = ready.to(delivering)
    precheck_failed = ready.to(failed)
    delivery_succeeded = delivering.to(delivered)
    delivery_failed = delivering.to(failed)
    # Closed-PR delivery guard: distinct from a user rejection so it can be
    # restored on PR reopen without an out-of-band delivered_at check. Fires
    # from ``ready`` (the delivery-time guard) and from ``delivered`` (the
    # pull_request ``closed`` webhook withdrawing an already-delivered fix).
    supersede_closed_pr = ready.to(superseded) | delivered.to(superseded)
    # The fix's target workflow file was deleted from the repo: fires from
    # every non-terminal, non-superseded state during missing-file
    # reconciliation. Distinct from ``supersede_closed_pr`` so it can be
    # restored independently if the same path reappears.
    supersede_deleted_file = (
        pending.to(superseded_deleted_file)
        | generating.to(superseded_deleted_file)
        | ready.to(superseded_deleted_file)
        | delivering.to(superseded_deleted_file)
        | delivered.to(superseded_deleted_file)
    )
    # User reject is legal from every state except the two terminal ones
    # (``failed`` and an already ``rejected_by_user`` fix). A repeated DELETE is
    # kept idempotent at the endpoint via ``try_advance`` rather than a
    # self-loop, so ``rejected_by_user`` stays a true final state.
    reject = (
        pending.to(rejected_by_user)
        | generating.to(rejected_by_user)
        | ready.to(rejected_by_user)
        | delivering.to(rejected_by_user)
        | delivered.to(rejected_by_user)
        | superseded.to(rejected_by_user)
        | superseded_deleted_file.to(rejected_by_user)
    )
    restore = superseded.to(ready) | superseded_deleted_file.to(ready)
    # In-place recovery for a failed fix: re-queue the same row for generation
    # instead of discarding it and inserting a new one. Not offered from
    # ``rejected_by_user`` — an explicit user dismissal stays terminal.
    regenerate = failed.to(pending)
    # The fix's PR merged: mark it landed and (at the call site) resolve its
    # issues with reason ``merged``. Fired from the pull_request merge webhook.
    land = delivered.to(landed)
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
        "supersede_deleted_file": SSESignal.fix_rejected,
        "reject": SSESignal.fix_rejected,
        "restore": None,
        "regenerate": SSESignal.fix_pending,
        "land": SSESignal.fix_landed,
        "swept": SSESignal.fix_failed,
    }
