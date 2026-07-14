"""Issue lifecycle state machine (``python-statemachine``).

``Issue.status`` is a persisted column maintained by a database trigger that
computes it from ``ignored_at``, ``resolved_at`` and ``fix_id`` (see the
``0022`` and ``0026`` migrations), so the column can never disagree with those
fields — even when ``fix_id`` is cleared by the ``ON DELETE SET NULL`` cascade
on fix deletion. ``ignored_at`` takes precedence: a user-muted violation stays
``ignored`` regardless of fix/resolve activity.

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
    ignored = State(value=IssueStatus.ignored)

    # Inputs (events) — each corresponds to a change of the underlying fields.
    link_fix = open.to(fix_in_progress)  # fix_id set (fix queued)
    unlink_fix = fix_in_progress.to(open)  # fix_id -> NULL (fix deleted)
    resolve = open.to(resolved) | fix_in_progress.to(resolved)  # resolved_at set
    recur = resolved.to(open)  # resolved_at -> NULL (violation reappears)
    ignore = open.to(ignored) | fix_in_progress.to(ignored)  # ignored_at set
    unignore = ignored.to(open)  # ignored_at -> NULL

    outputs: dict[str, None] = {
        "link_fix": None,
        "unlink_fix": None,
        "resolve": None,
        "recur": None,
        "ignore": None,
        "unignore": None,
    }
