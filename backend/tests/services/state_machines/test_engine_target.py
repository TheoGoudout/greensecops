"""The derived target-activity machine: statuses in, refusals out.

Table-driven because the rule *is* a table — one row per (activity, action)
pair — and because ``engine_target`` deliberately takes no session, so the whole
graph is exercisable without a database.
"""

import pytest

from app.models.enums import (
    FixStatus,
    ScanStatus,
    TargetAction,
    TargetActivity,
)
from app.services import state_machines as sm
from app.services.state_machines import engine_target

# ─── activity_of ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("scans", "fixes", "expected"),
    [
        pytest.param([], [], TargetActivity.idle, id="nothing-at-all"),
        pytest.param([None], [None], TargetActivity.idle, id="never-scanned"),
        pytest.param(
            [ScanStatus.completed],
            [FixStatus.ready, FixStatus.delivered, FixStatus.landed],
            TargetActivity.idle,
            id="settled-outcomes-are-not-activity",
        ),
        pytest.param(
            [ScanStatus.failed, ScanStatus.no_targets],
            [FixStatus.failed, FixStatus.rejected_by_user],
            TargetActivity.idle,
            id="failures-are-not-activity",
        ),
        pytest.param([ScanStatus.queued], [], TargetActivity.scanning, id="queued"),
        pytest.param([ScanStatus.running], [], TargetActivity.scanning, id="running"),
        pytest.param(
            [ScanStatus.completed, ScanStatus.running],
            [],
            TargetActivity.scanning,
            id="any-scan-not-just-the-first",
        ),
        pytest.param(
            [], [FixStatus.pending], TargetActivity.generating, id="pending-generates"
        ),
        pytest.param(
            [], [FixStatus.generating], TargetActivity.generating, id="generating"
        ),
        pytest.param(
            [], [FixStatus.delivering], TargetActivity.delivering, id="delivering"
        ),
    ],
)
def test_activity_of(
    scans: list[ScanStatus | None],
    fixes: list[FixStatus | None],
    expected: TargetActivity,
) -> None:
    assert sm.activity_of(scans, fixes) is expected


@pytest.mark.parametrize(
    ("scans", "fixes", "expected"),
    [
        pytest.param(
            [ScanStatus.running],
            [FixStatus.delivering, FixStatus.generating],
            TargetActivity.scanning,
            id="a-scan-outranks-everything",
        ),
        pytest.param(
            [ScanStatus.completed],
            [FixStatus.generating, FixStatus.delivering],
            TargetActivity.delivering,
            id="delivering-outranks-generating",
        ),
    ],
)
def test_activity_precedence(
    scans: list[ScanStatus],
    fixes: list[FixStatus],
    expected: TargetActivity,
) -> None:
    """Several things can be true at once; the reported one names the longest
    wait, so the message the user reads is the one worth waiting for."""
    assert sm.activity_of(scans, fixes) is expected


def test_activity_of_accepts_plain_strings() -> None:
    """A single-column ``select`` hands statuses back as bare strings; the
    machine has to read those as the enum members they are."""
    assert sm.activity_of(["running"]) is TargetActivity.scanning
    assert sm.activity_of([], ["delivering"]) is TargetActivity.delivering
    assert sm.activity_of(["completed"], ["ready"]) is TargetActivity.idle


# ─── blocked_reason ──────────────────────────────────────────────────────────

_ALLOWED = None

# One row per activity; the columns are the three actions in TargetAction order.
# ``_ALLOWED`` means the action goes through.
_MATRIX: dict[TargetActivity, tuple[str | None, str | None, str | None]] = {
    TargetActivity.idle: (_ALLOWED, _ALLOWED, _ALLOWED),
    TargetActivity.scanning: (
        "a scan is already running",
        "a scan is already running",
        "a scan is already running",
    ),
    # Generating is the one activity that still allows generating: writing a fix
    # for file B while file A's is in flight is ordinary work.
    TargetActivity.generating: (
        "fixes are being generated",
        _ALLOWED,
        "fixes are being generated",
    ),
    TargetActivity.delivering: (
        "a pull request is being opened",
        "a pull request is being opened",
        "a pull request is being opened",
    ),
}


@pytest.mark.parametrize("activity", list(_MATRIX))
def test_blocked_reason_matrix(activity: TargetActivity) -> None:
    scan, generate, deliver = _MATRIX[activity]
    assert sm.blocked_reason(activity, TargetAction.scan) == scan
    assert sm.blocked_reason(activity, TargetAction.generate) == generate
    assert sm.blocked_reason(activity, TargetAction.deliver) == deliver


def test_every_activity_and_action_is_covered() -> None:
    """The matrix above is the specification, so it has to stay exhaustive —
    a new activity or action must not slip through untested."""
    assert set(_MATRIX) == set(TargetActivity)
    assert set(engine_target.BLOCKS) == set(TargetAction)
    assert set(engine_target.REASONS) == set(TargetActivity) - {TargetActivity.idle}


def test_in_flight_fix_statuses_all_report_an_activity() -> None:
    """Mirrors the import-time assertion: a status ``FixMachine`` calls
    in-flight must map to an activity, or a busy target would read as idle."""
    for status in sm.IN_FLIGHT_STATUSES:
        assert sm.activity_of([], [status]) is not TargetActivity.idle
