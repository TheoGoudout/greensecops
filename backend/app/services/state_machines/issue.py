"""Issue lifecycle state machine (``python-statemachine``).

``Issue.status`` is a persisted column maintained by a database trigger that
computes it from ``resolved_at`` and ``fix_id`` (see the ``0022`` migration), so
the column can never disagree with those fields — even when ``fix_id`` is
cleared by the ``ON DELETE SET NULL`` cascade on fix deletion.

This machine is therefore the canonical, testable declaration of the legal
field-level transitions the rest of the code performs; it documents and
validates the graph rather than mutating rows itself (the trigger owns writes).

States mirror ``IssueStatus``. Behaviour lives in ``static_analysis.py`` and the
fix routes.
"""

from __future__ import annotations

from statemachine import State, StateMachine

from app.models.enums import IssueStatus


class IssueMachine(StateMachine):
    state_field = "status"

    open = State(initial=True, value=IssueStatus.open)
    fix_in_progress = State(value=IssueStatus.fix_in_progress)
    resolved = State(value=IssueStatus.resolved)

    # Inputs (events) — each corresponds to a change of resolved_at / fix_id.
    link_fix = open.to(fix_in_progress)  # fix_id set (fix queued)
    unlink_fix = fix_in_progress.to(open)  # fix_id -> NULL (fix deleted)
    resolve = open.to(resolved) | fix_in_progress.to(resolved)  # resolved_at set
    recur = resolved.to(open)  # resolved_at -> NULL (violation reappears)

    outputs: dict[str, None] = {
        "link_fix": None,
        "unlink_fix": None,
        "resolve": None,
        "recur": None,
    }
