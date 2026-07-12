"""Pull-request lifecycle state machine.

Mirrors ``PullRequestState`` and the behaviour in ``fix_delivery.py``, the
``pull_request`` webhook handler, ``maintenance.sync_open_pr_states`` and
``fixes.sync_pr_statuses``.

Known gaps (see ``docs/state-machines.md``), preserved here as-is:

* ``pr_state`` is nullable — legacy records may carry ``NULL``. ``NULL`` is not
  a member of the state enum; creation and reconciliation set an explicit
  state, so it is treated as an out-of-band "unknown" rather than a machine
  state.
* Only ``closed`` and ``reopened`` ``pull_request`` webhook actions are
  handled; ``synchronize`` / ``edited`` are not modelled.

PR creation and the "ensure open on re-delivery" reconciliation happen at the
delivery boundary (``fix_delivery.py``) as initialisation, not as guarded
transitions; ``redeliver`` is declared here to document that self-loop. The
genuine lifecycle transitions — ``merge``, ``close``, ``reopen`` — are routed
through :meth:`StateMachine.trigger`.
"""

from __future__ import annotations

import enum

from app.models.enums import PullRequestState, SSESignal

from .base import StateMachine, Transition


class PullRequestEvent(str, enum.Enum):
    """Inputs that drive a pull request between states."""

    redeliver = "redeliver"  # a new delivery updated the open PR branch
    merge = "merge"  # PR merged (webhook / reconcile)
    close = "close"  # PR closed without merging (webhook / reconcile)
    reopen = "reopen"  # PR reopened (webhook)


_transitions: tuple[Transition[PullRequestState, PullRequestEvent], ...] = (
    Transition(
        event=PullRequestEvent.redeliver,
        sources=frozenset({PullRequestState.open}),
        dest=PullRequestState.open,
        output=SSESignal.pr_updated,
        description="A subsequent delivery updated the open PR's branch.",
    ),
    Transition(
        event=PullRequestEvent.merge,
        sources=frozenset({PullRequestState.open}),
        dest=PullRequestState.merged,
        output=SSESignal.pr_merged,
        description="PR was merged (via webhook or missed-webhook reconcile).",
    ),
    Transition(
        event=PullRequestEvent.close,
        sources=frozenset({PullRequestState.open}),
        dest=PullRequestState.closed,
        output=SSESignal.pr_closed,
        description="PR was closed without merging; a rejection signal.",
    ),
    Transition(
        event=PullRequestEvent.reopen,
        sources=frozenset({PullRequestState.closed}),
        dest=PullRequestState.open,
        output=SSESignal.pr_opened,
        description="Closed PR was reopened; guard-rejected fixes become "
        "deliverable again.",
    ),
)

pull_request_machine: StateMachine[PullRequestState, PullRequestEvent] = StateMachine(
    name="pull_request",
    state_attr="pr_state",
    state_enum=PullRequestState,
    event_enum=PullRequestEvent,
    transitions=_transitions,
    initial_states=frozenset({PullRequestState.open}),
    terminal_states=frozenset({PullRequestState.merged}),
)
