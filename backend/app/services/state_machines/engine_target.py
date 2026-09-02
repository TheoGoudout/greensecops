"""What a scan target is busy with, and which actions that forbids.

The other machines in this package drive a **persisted** column: a scan row's
``status``, a fix row's ``status``. This one is derived. A target — a Terraform
root, a Docker target, an Ansible project, a cloud account, a workflow file, or
a whole repository on the CI engine — has no status column of its own; what it
is *doing* is the union of its latest scan's status and its fixes' statuses.

That union is nonetheless a state machine, and it is the one the user actually
interacts with. Every engine offers the same three actions (``POST .../scans``,
``POST .../fixes``, ``POST .../deliveries``) and every one of them used to
accept a request that collided with work already in flight: a second scan
returned ``202`` and was then silently swallowed by the Redis lock in the
worker, and fix generation happily started against findings a running scan was
about to replace.

::

                              ┌──────────┐
                              │   idle   │   scan ✓  generate ✓  deliver ✓
                              └────┬─────┘
           scan queued/running     │     fix pending/generating
                  ┌────────────────┼────────────────┐
                  │                │                │ fix delivering
                  ▼                ▼                ▼
            ┌──────────┐    ┌────────────┐    ┌────────────┐
            │ scanning │    │ generating │    │ delivering │
            │ ✗ ✗ ✗    │    │ ✗ ✓ ✗      │    │ ✗ ✗ ✗      │
            └──────────┘    └────────────┘    └────────────┘

``generate`` is the one action a ``generating`` target still allows: writing a
fix for file B while file A's is in flight is ordinary, and
``prepare_pending_fix`` already declines to reset a file whose own fix a worker
holds. Everything else is one-at-a-time, because the alternative is a scan
rewriting the findings an LLM is being prompted with, or a pull request opened
without the fixes still being written into it.

The **scope** the statuses are collected over is the caller's business, and it
is the unit the action addresses: one file, one registered target, or a whole
repository on the CI engine. This module only turns statuses into an activity
and an activity into a refusal — it touches no session, which is what keeps it
testable as a table.

``api/engine_routes.require_target_idle`` is the HTTP half; the frontend states
the same rules in ``frontend/src/lib/engine-actions.ts``, and the two reason
strings are kept identical on purpose so a 409 that races past the disabled
button reads exactly like the tooltip that should have stopped it.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.models.enums import (
    FixStatus,
    ScanStatus,
    TargetAction,
    TargetActivity,
)

from .fix import IN_FLIGHT_STATUSES

# Scan statuses that mean a worker holds this target — the same two
# ``scan-polling.ts`` polls on. ``failed`` and ``no_targets`` are finished
# outcomes, not activity.
ACTIVE_SCAN_STATUSES: frozenset[ScanStatus] = frozenset(
    {ScanStatus.queued, ScanStatus.running}
)

# Which activity each in-flight fix status reports. ``pending`` counts as
# generating: the row is queued for an LLM call that has not started, and a scan
# landing in between would invalidate the findings it is about to be given.
#
# Keyed by ``str`` rather than by ``FixStatus`` because callers select the
# status column on its own (``select(Fix.status)``), which SQLModel types as a
# bare ``str`` — and these are ``str`` enums, so the member and its value are the
# same key either way.
_FIX_ACTIVITY: dict[str, TargetActivity] = {
    FixStatus.pending: TargetActivity.generating,
    FixStatus.generating: TargetActivity.generating,
    FixStatus.delivering: TargetActivity.delivering,
}

# Reported when several hold at once. A scan outranks fix work because it
# rewrites what the fixes are about; a delivery outranks generation because it
# is the shorter, closer-to-done one and names the more specific wait.
_PRECEDENCE: tuple[TargetActivity, ...] = (
    TargetActivity.scanning,
    TargetActivity.delivering,
    TargetActivity.generating,
)

# The rule itself: which activities refuse which action.
BLOCKS: dict[TargetAction, frozenset[TargetActivity]] = {
    TargetAction.scan: frozenset(
        {
            TargetActivity.scanning,
            TargetActivity.generating,
            TargetActivity.delivering,
        }
    ),
    TargetAction.generate: frozenset(
        {TargetActivity.scanning, TargetActivity.delivering}
    ),
    TargetAction.deliver: frozenset(
        {
            TargetActivity.scanning,
            TargetActivity.generating,
            TargetActivity.delivering,
        }
    ),
}

# How each activity names itself in a refusal. Written to read as the middle of
# "Cannot generate fixes while <reason> for this Terraform root".
REASONS: dict[TargetActivity, str] = {
    TargetActivity.scanning: "a scan is already running",
    TargetActivity.generating: "fixes are being generated",
    TargetActivity.delivering: "a pull request is being opened",
}


# The two ways of saying "a worker holds this fix" must stay one thing: every
# status ``FixMachine`` calls in-flight has to report an activity here, or a
# target would look idle while a worker was mid-write. Checked at import in the
# same spirit as ``services/engines.py``'s ``_SPECS_AGREE``.
assert set(_FIX_ACTIVITY) == {s.value for s in IN_FLIGHT_STATUSES}, (
    "engine_target._FIX_ACTIVITY and FixMachine's IN_FLIGHT_STATUSES disagree"
)


def activity_of(
    scan_statuses: Iterable[ScanStatus | str | None],
    fix_statuses: Iterable[FixStatus | str | None] = (),
) -> TargetActivity:
    """What the scope covered by these statuses is currently busy with.

    Both arguments are whole collections rather than a single "latest" value:
    a repository-scoped action looks at every workflow file's scan, and a
    target-scoped one at every fix under it. Passing one status is the
    degenerate case, not a different call.

    Plain strings are accepted alongside the enums for the reason given on
    ``_FIX_ACTIVITY``: a single-column ``select`` hands these back typed as
    ``str``, and comparing a ``str`` enum against its own value is exact.
    """
    found: set[TargetActivity] = set()
    for scan_status in scan_statuses:
        if scan_status is not None and scan_status in ACTIVE_SCAN_STATUSES:
            found.add(TargetActivity.scanning)
            break
    for fix_status in fix_statuses:
        activity = _FIX_ACTIVITY.get(fix_status) if fix_status is not None else None
        if activity is not None:
            found.add(activity)
    for candidate in _PRECEDENCE:
        if candidate in found:
            return candidate
    return TargetActivity.idle


def blocked_reason(activity: TargetActivity, action: TargetAction) -> str | None:
    """Why ``action`` is refused right now, or ``None`` if it is allowed."""
    if activity in BLOCKS[action]:
        return REASONS[activity]
    return None
