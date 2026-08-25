"""Terraform/Docker/cloud finding lifecycle state machine (``python-statemachine``).

States mirror ``FindingStatus``. Shared by ``TerraformFinding.status``,
``DockerFinding.status`` and ``CloudFinding.status``. Unlike ``WorkflowFinding.status``
— a DB-trigger-derived column reacting to ``fix_id``/``resolved_at``/
``ignored_at``, with ``FindingMachine`` only documenting the graph — this
``status`` is written directly by the application via ``sm.advance``, the way
``ScanMachine`` does, because there is no trigger to keep in sync.

Note that Terraform and Docker findings *do* now have fixes
(``TerraformFix``/``DockerFix``), but a fix keys on a ``(target, file_path)``
pair rather than on the finding, so it never reaches back into this graph.

Only ``resolve`` is currently fired, by
``services/scan_support.resolve_stale_findings`` on behalf of the Terraform,
Docker and cloud workers. ``recur`` is bypassed: those workers reopen a finding
by setting ``resolved_at = NULL`` inside the ``ON CONFLICT DO UPDATE`` of their
upsert, which never passes through this machine. ``ignore``/``unignore`` have
no caller at all — no route exposes ``ignored_at`` for these engines, unlike
``WorkflowFinding`` (``api/routes/issues.py``, plus the PR-comment commands in
``services/github/event_handlers.py``). Both are declared, tested edges waiting
on the routes that will fire them.
"""

from __future__ import annotations

from statemachine import State, StateMachine

from app.models.enums import FindingStatus


class FindingMachine(StateMachine):
    state_field = "status"

    open = State(initial=True, value=FindingStatus.open)
    fix_in_progress = State(value=FindingStatus.fix_in_progress)
    resolved = State(value=FindingStatus.resolved)
    ignored = State(value=FindingStatus.ignored)

    # Inputs (events) — each corresponds to a change of the underlying fields.
    # `link_fix`/`unlink_fix` came from the merged FindingMachine and are reachable
    # only on the CI engine, whose findings carry a `fix_id`; the other engines
    # key a fix on `(target, file_path)` and never touch this pair.
    link_fix = open.to(fix_in_progress)  # fix_id set (fix queued)
    unlink_fix = fix_in_progress.to(open)  # fix_id -> NULL (fix deleted)
    resolve = open.to(resolved) | fix_in_progress.to(resolved)  # resolved_at set
    recur = resolved.to(open)  # resolved_at -> NULL (violation reappears)
    ignore = open.to(ignored) | fix_in_progress.to(ignored)  # ignored_at set
    unignore = ignored.to(open)  # ignored_at -> NULL

    # No SSE wiring yet — same rationale as ScanMachine.
    outputs: dict[str, None] = {
        "link_fix": None,
        "unlink_fix": None,
        "resolve": None,
        "recur": None,
        "ignore": None,
        "unignore": None,
    }
