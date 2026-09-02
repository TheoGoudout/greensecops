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
                              │   idle   │  everything allowed
                              └────┬─────┘
           scan queued/running     │     fix pending/generating
                  ┌────────────────┼────────────────┐
                  │                │                │ fix delivering
                  ▼                ▼                ▼
            ┌──────────┐    ┌────────────┐    ┌────────────┐
            │ scanning │    │ generating │    │ delivering │
            └──────────┘    └────────────┘    └────────────┘

                       scan  generate  deliver  remove  ignore  sync
            scanning     ✗       ✗        ✗       ✗       ✗      ✗
            generating   ✗       ✓        ✗       ✗       ✓      ✓
            delivering   ✗       ✗        ✗       ✗       ✓      ✓

``generate`` is the one *engine* action a ``generating`` target still allows:
writing a fix for file B while file A's is in flight is ordinary, and
``prepare_pending_fix`` already declines to reset a file whose own fix a worker
holds. The other three engine actions are one-at-a-time, because the
alternative is a scan rewriting the findings an LLM is being prompted with, a
pull request opened without the fixes still being written into it, or a target
deleted out from under a worker still writing its rows.

``ignore`` and ``sync`` are the two actions a scan alone refuses. They are not
engine flows — muting a violation, re-fetching a repository's workflow files —
but they touch exactly what a scan rewrites: ``resolve_stale_findings`` can move
a finding out from under the ignore transition, and ``static_analysis`` holds
``WorkflowFile.raw_content`` under a repo-wide lock. Fix generation and delivery
read those and write neither, so they let both through.

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

_BUSY = frozenset(
    {
        TargetActivity.scanning,
        TargetActivity.generating,
        TargetActivity.delivering,
    }
)

# The rule itself: which activities refuse which action.
#
# ``remove`` joins the one-at-a-time majority: deleting a target cascades its
# scans, findings and fixes away (``ondelete="CASCADE"``), and a worker holding
# any of them is mid-write.
#
# ``ignore`` and ``sync`` are refused by a scan alone. A scan is the only
# activity that touches what they touch — ``resolve_stale_findings`` moves a
# finding out from under the ignore transition, and ``static_analysis`` rewrites
# the very ``WorkflowFile.raw_content`` a sync would replace, which is what its
# repo-wide Redis lock already protects. Fix work reads findings and files but
# writes neither, so muting a violation while another file's fix is being
# written is ordinary.
BLOCKS: dict[TargetAction, frozenset[TargetActivity]] = {
    TargetAction.scan: _BUSY,
    TargetAction.generate: frozenset(
        {TargetActivity.scanning, TargetActivity.delivering}
    ),
    TargetAction.deliver: _BUSY,
    TargetAction.remove: _BUSY,
    TargetAction.ignore: frozenset({TargetActivity.scanning}),
    TargetAction.sync: frozenset({TargetActivity.scanning}),
}

# Every action has a rule. A new ``TargetAction`` whose author forgot this table
# would otherwise raise ``KeyError`` inside ``blocked_reason`` on the first
# request that reached it, which is a 500 where the whole point of this module
# is a 409.
assert set(BLOCKS) == set(TargetAction), (
    "engine_target.BLOCKS is missing a TargetAction"
)

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
