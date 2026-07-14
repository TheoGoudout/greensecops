"""Pull-request lifecycle state machine (``python-statemachine``).

States mirror ``PullRequestState``. Behaviour lives in ``fix_delivery.py``, the
``pull_request`` webhook handler, ``maintenance.sync_open_pr_states`` and
``fixes.sync_pr_statuses``.

PR creation and the "ensure open on re-delivery" reconciliation happen at the
delivery boundary as initialisation, not guarded transitions. ``pr_state`` is
nullable — legacy rows may carry ``NULL``; :func:`base.try_advance` treats such
a row as non-transitionable rather than raising.
"""

from __future__ import annotations

from statemachine import State, StateMachine

from app.models.enums import PullRequestState, SSESignal


class PullRequestMachine(StateMachine):
    state_field = "pr_state"

    open = State(initial=True, value=PullRequestState.open)
    draft = State(value=PullRequestState.draft)
    merged = State(value=PullRequestState.merged, final=True)
    closed = State(value=PullRequestState.closed)

    # Inputs (events)
    redeliver = open.to.itself()  # type: ignore[no-untyped-call]
    external_update = open.to.itself() | draft.to.itself()  # type: ignore[no-untyped-call]
    # GitHub draft toggles (converted_to_draft / ready_for_review).
    convert_to_draft = open.to(draft)
    mark_ready_for_review = draft.to(open)
    # A draft PR can still be merged or closed directly on GitHub.
    merge = open.to(merged) | draft.to(merged)
    close = open.to(closed) | draft.to(closed)
    reopen = closed.to(open)

    # Outputs (SSE signal emitted when each event fires)
    outputs: dict[str, SSESignal | None] = {
        "redeliver": SSESignal.pr_updated,
        "external_update": SSESignal.pr_updated,
        "convert_to_draft": SSESignal.pr_updated,
        "mark_ready_for_review": SSESignal.pr_updated,
        "merge": SSESignal.pr_merged,
        "close": SSESignal.pr_closed,
        "reopen": SSESignal.pr_opened,
    }
