"""Terraform/cloud finding lifecycle state machine (``python-statemachine``).

States mirror ``FindingStatus``. Shared by ``TerraformFinding.status`` and
``CloudFinding.status``. Unlike ``Issue.status`` (a DB-trigger-derived column
reacting to ``fix_id``/``resolved_at``/``ignored_at``, with ``IssueMachine``
only documenting the graph), findings in this delivery have no fix/PR concept
yet (see the IaC/cloud plan's Phase 7), so this machine directly drives writes
via ``sm.advance`` the way ``AnalysisMachine`` does — there is no trigger to
keep in sync.

Behaviour lands with the terraform_analysis.py/cloud_analysis.py worker tasks
and the finding ignore/unignore API routes (later phases).
"""

from __future__ import annotations

from statemachine import State, StateMachine

from app.models.enums import FindingStatus


class FindingMachine(StateMachine):
    state_field = "status"

    open = State(initial=True, value=FindingStatus.open)
    resolved = State(value=FindingStatus.resolved)
    ignored = State(value=FindingStatus.ignored)

    # Inputs (events) — each corresponds to a change of the underlying fields.
    resolve = open.to(resolved)  # resolved_at set (no longer seen / target removed)
    recur = resolved.to(open)  # resolved_at -> NULL (violation reappears)
    ignore = open.to(ignored)  # ignored_at set (user dismissed)
    unignore = ignored.to(open)  # ignored_at -> NULL

    # No SSE wiring yet — same rationale as ScanMachine.
    outputs: dict[str, None] = {
        "resolve": None,
        "recur": None,
        "ignore": None,
        "unignore": None,
    }
