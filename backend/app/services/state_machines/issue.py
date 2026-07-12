"""Issue lifecycle state machine.

Issues carry **no status column**; their state is derived from ``resolved_at``
and ``fix_id`` via :attr:`app.models.db.Issue.status` (see
:class:`app.models.enums.IssueStatus`). This machine is therefore the
canonical, testable declaration of the field-level transitions the rest of the
code performs on those two columns — the derived property guarantees only valid
states can ever be observed.

Known gaps (see ``docs/state-machines.md``), preserved here as-is:

* There is no ``ignored`` / ``muted`` state — ``/greensecops ignore`` is parsed
  but unimplemented, so a user cannot dismiss a false positive.
* ``resolved`` records no reason (user fix vs. rule disabled vs. merged).
"""

from __future__ import annotations

import enum

from app.models.enums import IssueStatus

from .base import StateMachine, Transition


class IssueEvent(str, enum.Enum):
    """Inputs that drive an issue between derived states."""

    link_fix = "link_fix"  # a fix was queued for this issue (fix_id set)
    unlink_fix = "unlink_fix"  # the fix was deleted/regenerated (fix_id -> NULL)
    resolve = "resolve"  # not reported by latest run / file deleted / user fix
    recur = "recur"  # the same violation was found again (resolved_at -> NULL)


_transitions: tuple[Transition[IssueStatus, IssueEvent], ...] = (
    Transition(
        event=IssueEvent.link_fix,
        sources=frozenset({IssueStatus.open}),
        dest=IssueStatus.fix_in_progress,
        description="Fix generation was queued; issue linked via fix_id.",
    ),
    Transition(
        event=IssueEvent.unlink_fix,
        sources=frozenset({IssueStatus.fix_in_progress}),
        dest=IssueStatus.open,
        description="Fix deleted/regenerated; fix_id cleared (ON DELETE SET NULL).",
    ),
    Transition(
        event=IssueEvent.resolve,
        sources=frozenset({IssueStatus.open, IssueStatus.fix_in_progress}),
        dest=IssueStatus.resolved,
        description="Issue no longer reported by the latest analysis.",
    ),
    Transition(
        event=IssueEvent.recur,
        sources=frozenset({IssueStatus.resolved}),
        # A recurrence only clears resolved_at; if fix_id survives, the derived
        # status returns to fix_in_progress, otherwise open. Declared to `open`
        # as the common case (recurrence typically follows fix deletion).
        dest=IssueStatus.open,
        description="A previously resolved violation was found again.",
    ),
)

issue_machine: StateMachine[IssueStatus, IssueEvent] = StateMachine(
    name="issue",
    state_attr="status",  # read-only derived property; use for can()/next_state()
    state_enum=IssueStatus,
    event_enum=IssueEvent,
    transitions=_transitions,
    initial_states=frozenset({IssueStatus.open}),
    terminal_states=frozenset({IssueStatus.resolved}),
)
