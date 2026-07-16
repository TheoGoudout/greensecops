"""Behavioural tests for the four lifecycle state machines."""

import pytest
from statemachine import StateMachine

from app.models.enums import (
    AnalysisStatus,
    DynamicAnalysisStatus,
    FixStatus,
    IssueStatus,
    PullRequestState,
    RepositoryStatus,
    SSESignal,
)
from app.services import state_machines as sm

ALL_MACHINES = [
    sm.AnalysisMachine,
    sm.FixMachine,
    sm.PullRequestMachine,
    sm.IssueMachine,
    sm.RepositoryMachine,
    sm.TelemetryMachine,
]


class _Model:
    """Minimal stand-in that holds a state in the machine's state_field."""

    def __init__(self, machine_cls: type[StateMachine], value: object) -> None:
        setattr(self, machine_cls.state_field, value)  # type: ignore[attr-defined]


# ── Structural invariants shared by every machine ────────────────────────────


@pytest.mark.parametrize("machine", ALL_MACHINES, ids=lambda m: m.name)
def test_machine_graph_is_valid(machine: type[StateMachine]) -> None:
    # python-statemachine validates connectivity and a single initial state at
    # class-definition time; a machine object existing at all proves the graph.
    assert machine.states
    initials = [s for s in machine.states if s.initial]
    assert len(initials) == 1


@pytest.mark.parametrize("machine", ALL_MACHINES, ids=lambda m: m.name)
def test_state_values_are_the_status_enums(machine: type[StateMachine]) -> None:
    for state in machine.states:
        # Each state carries the persisted enum value it maps to.
        assert state.value is not None


@pytest.mark.parametrize("machine", ALL_MACHINES, ids=lambda m: m.name)
def test_declared_outputs_reference_known_events(
    machine: type[StateMachine],
) -> None:
    event_ids = {e.id for e in machine.events}
    for event_id, signal in machine.outputs.items():  # type: ignore[attr-defined]
        assert event_id in event_ids
        assert signal is None or isinstance(signal, SSESignal)


# ── Analysis ─────────────────────────────────────────────────────────────────


def test_analysis_happy_path() -> None:
    a = _Model(sm.AnalysisMachine, AnalysisStatus.queued)
    assert sm.advance(a, sm.AnalysisMachine, "started") is AnalysisStatus.running
    assert (
        sm.advance(a, sm.AnalysisMachine, "opa_succeeded") is AnalysisStatus.completed
    )


def test_analysis_queued_is_initial() -> None:
    assert sm.AnalysisMachine.initial_state.value is AnalysisStatus.queued


def test_analysis_no_workflows_edge() -> None:
    a = _Model(sm.AnalysisMachine, AnalysisStatus.running)
    assert (
        sm.advance(a, sm.AnalysisMachine, "no_workflows_found")
        is AnalysisStatus.no_workflows
    )


def test_analysis_sweep_from_queued_or_running() -> None:
    for src in (AnalysisStatus.queued, AnalysisStatus.running):
        a = _Model(sm.AnalysisMachine, src)
        assert sm.advance(a, sm.AnalysisMachine, "swept") is AnalysisStatus.failed


def test_analysis_cannot_advance_from_terminal() -> None:
    a = _Model(sm.AnalysisMachine, AnalysisStatus.completed)
    with pytest.raises(sm.IllegalTransition):
        sm.advance(a, sm.AnalysisMachine, "opa_succeeded")


def test_analysis_retry_requeues_a_failed_row() -> None:
    a = _Model(sm.AnalysisMachine, AnalysisStatus.failed)
    assert sm.advance(a, sm.AnalysisMachine, "retry") is AnalysisStatus.queued
    # A completed analysis has no retry edge.
    a2 = _Model(sm.AnalysisMachine, AnalysisStatus.completed)
    with pytest.raises(sm.IllegalTransition):
        sm.advance(a2, sm.AnalysisMachine, "retry")


# ── Fix ──────────────────────────────────────────────────────────────────────


def test_fix_generation_and_delivery_path() -> None:
    f = _Model(sm.FixMachine, FixStatus.pending)
    for event, expected in [
        ("start_generation", FixStatus.generating),
        ("generation_succeeded", FixStatus.ready),
        ("start_delivery", FixStatus.delivering),
        ("delivery_succeeded", FixStatus.delivered),
    ]:
        assert sm.advance(f, sm.FixMachine, event) is expected


def test_fix_reject_lands_in_rejected_by_user() -> None:
    for src in (
        FixStatus.ready,
        FixStatus.delivered,
        FixStatus.superseded_by_closed_pr,
        FixStatus.superseded_by_deleted_file,
    ):
        f = _Model(sm.FixMachine, src)
        assert sm.advance(f, sm.FixMachine, "reject") is FixStatus.rejected_by_user


def test_fix_reject_is_terminal_double_reject_is_illegal() -> None:
    # rejected_by_user is a true final state; the DELETE route makes a repeated
    # reject idempotent via try_advance, not a machine self-loop.
    f = _Model(sm.FixMachine, FixStatus.rejected_by_user)
    with pytest.raises(sm.IllegalTransition):
        sm.advance(f, sm.FixMachine, "reject")


def test_fix_supersede_from_ready_or_delivered() -> None:
    # Closed-PR guard fires both at delivery time (from ``ready``) and when the
    # pull_request ``closed`` webhook withdraws an already-``delivered`` fix.
    for src in (FixStatus.ready, FixStatus.delivered):
        f = _Model(sm.FixMachine, src)
        assert (
            sm.advance(f, sm.FixMachine, "supersede_closed_pr")
            is FixStatus.superseded_by_closed_pr
        )
    # Not legal from an in-flight or terminal state.
    f2 = _Model(sm.FixMachine, FixStatus.generating)
    with pytest.raises(sm.IllegalTransition):
        sm.advance(f2, sm.FixMachine, "supersede_closed_pr")


def test_fix_supersede_deleted_file_from_any_non_terminal_state() -> None:
    # Missing-file reconciliation may find the fix in any non-terminal state.
    for src in (
        FixStatus.pending,
        FixStatus.generating,
        FixStatus.ready,
        FixStatus.delivering,
        FixStatus.delivered,
    ):
        f = _Model(sm.FixMachine, src)
        assert (
            sm.advance(f, sm.FixMachine, "supersede_deleted_file")
            is FixStatus.superseded_by_deleted_file
        )
    # Not legal once already rejected or landed.
    for src in (FixStatus.rejected_by_user, FixStatus.landed):
        f2 = _Model(sm.FixMachine, src)
        with pytest.raises(sm.IllegalTransition):
            sm.advance(f2, sm.FixMachine, "supersede_deleted_file")


def test_fix_regenerate_from_failed_only() -> None:
    f = _Model(sm.FixMachine, FixStatus.failed)
    assert sm.advance(f, sm.FixMachine, "regenerate") is FixStatus.pending
    # A user dismissal stays terminal — no in-place regenerate.
    f2 = _Model(sm.FixMachine, FixStatus.rejected_by_user)
    with pytest.raises(sm.IllegalTransition):
        sm.advance(f2, sm.FixMachine, "regenerate")


def test_fix_restore_only_from_superseded_not_user_rejected() -> None:
    for src in (
        FixStatus.superseded_by_closed_pr,
        FixStatus.superseded_by_deleted_file,
    ):
        f = _Model(sm.FixMachine, src)
        assert sm.advance(f, sm.FixMachine, "restore") is FixStatus.ready
    # A user rejection is final — reopening a PR must not resurrect it.
    f2 = _Model(sm.FixMachine, FixStatus.rejected_by_user)
    with pytest.raises(sm.IllegalTransition):
        sm.advance(f2, sm.FixMachine, "restore")


def test_fix_land_from_delivered_only() -> None:
    f = _Model(sm.FixMachine, FixStatus.delivered)
    assert sm.advance(f, sm.FixMachine, "land") is FixStatus.landed
    # A landed fix is terminal.
    with pytest.raises(sm.IllegalTransition):
        sm.advance(f, sm.FixMachine, "land")
    # Only a delivered fix can land (a merged PR of an undelivered fix is a
    # contradiction).
    f2 = _Model(sm.FixMachine, FixStatus.ready)
    with pytest.raises(sm.IllegalTransition):
        sm.advance(f2, sm.FixMachine, "land")


def test_fix_sweep_from_in_flight_only() -> None:
    for src in (FixStatus.pending, FixStatus.generating, FixStatus.delivering):
        f = _Model(sm.FixMachine, src)
        assert sm.advance(f, sm.FixMachine, "swept") is FixStatus.failed
    f2 = _Model(sm.FixMachine, FixStatus.ready)
    with pytest.raises(sm.IllegalTransition):
        sm.advance(f2, sm.FixMachine, "swept")


def test_in_flight_statuses_constant() -> None:
    assert sm.IN_FLIGHT_STATUSES == frozenset(
        {FixStatus.pending, FixStatus.generating, FixStatus.delivering}
    )


def test_rejected_statuses_constant() -> None:
    assert sm.REJECTED_STATUSES == frozenset(
        {
            FixStatus.rejected_by_user,
            FixStatus.superseded_by_closed_pr,
            FixStatus.superseded_by_deleted_file,
        }
    )


# ── Pull request ─────────────────────────────────────────────────────────────


def test_pull_request_lifecycle() -> None:
    pr = _Model(sm.PullRequestMachine, PullRequestState.open)
    assert sm.advance(pr, sm.PullRequestMachine, "close") is PullRequestState.closed
    assert sm.advance(pr, sm.PullRequestMachine, "reopen") is PullRequestState.open
    assert sm.advance(pr, sm.PullRequestMachine, "merge") is PullRequestState.merged


def test_pull_request_cannot_reopen_a_merged_pr() -> None:
    pr = _Model(sm.PullRequestMachine, PullRequestState.merged)
    with pytest.raises(sm.IllegalTransition):
        sm.advance(pr, sm.PullRequestMachine, "reopen")


def test_pull_request_draft_toggle() -> None:
    pr = _Model(sm.PullRequestMachine, PullRequestState.open)
    assert (
        sm.advance(pr, sm.PullRequestMachine, "convert_to_draft")
        is PullRequestState.draft
    )
    # A draft PR can still merge or be marked ready.
    assert (
        sm.advance(pr, sm.PullRequestMachine, "mark_ready_for_review")
        is PullRequestState.open
    )
    d = _Model(sm.PullRequestMachine, PullRequestState.draft)
    assert sm.advance(d, sm.PullRequestMachine, "merge") is PullRequestState.merged


# ── Repository ───────────────────────────────────────────────────────────────


def test_repository_suspend_unsuspend() -> None:
    r = _Model(sm.RepositoryMachine, RepositoryStatus.active)
    assert sm.advance(r, sm.RepositoryMachine, "suspend") is RepositoryStatus.suspended
    assert sm.advance(r, sm.RepositoryMachine, "unsuspend") is RepositoryStatus.active


def test_repository_archive_and_lose_access() -> None:
    r = _Model(sm.RepositoryMachine, RepositoryStatus.active)
    assert sm.advance(r, sm.RepositoryMachine, "archive") is RepositoryStatus.archived
    assert sm.advance(r, sm.RepositoryMachine, "unarchive") is RepositoryStatus.active
    for src in (
        RepositoryStatus.active,
        RepositoryStatus.suspended,
        RepositoryStatus.archived,
    ):
        r2 = _Model(sm.RepositoryMachine, src)
        assert (
            sm.advance(r2, sm.RepositoryMachine, "lose_access")
            is RepositoryStatus.inaccessible
        )
    assert (
        sm.advance(r2, sm.RepositoryMachine, "regain_access") is RepositoryStatus.active
    )


def test_repository_sync_access_flag() -> None:
    class _Repo:
        status = RepositoryStatus.active
        is_accessible = False

    repo = _Repo()
    sm.sync_access_flag(repo)
    assert repo.is_accessible is True
    repo.status = RepositoryStatus.suspended
    sm.sync_access_flag(repo)
    assert repo.is_accessible is False


# ── Telemetry (dynamic analysis) ─────────────────────────────────────────────


def test_telemetry_happy_path() -> None:
    t = _Model(sm.TelemetryMachine, DynamicAnalysisStatus.queued)
    assert (
        sm.advance(t, sm.TelemetryMachine, "started") is DynamicAnalysisStatus.running
    )
    assert (
        sm.advance(t, sm.TelemetryMachine, "enrich") is DynamicAnalysisStatus.enriched
    )


def test_telemetry_failure_and_retry() -> None:
    t = _Model(sm.TelemetryMachine, DynamicAnalysisStatus.running)
    assert sm.advance(t, sm.TelemetryMachine, "fail") is DynamicAnalysisStatus.failed
    assert sm.advance(t, sm.TelemetryMachine, "retry") is DynamicAnalysisStatus.queued
    # enriched is terminal.
    e = _Model(sm.TelemetryMachine, DynamicAnalysisStatus.enriched)
    with pytest.raises(sm.IllegalTransition):
        sm.advance(e, sm.TelemetryMachine, "retry")


def test_telemetry_sweep_from_queued_or_running() -> None:
    for src in (DynamicAnalysisStatus.queued, DynamicAnalysisStatus.running):
        t = _Model(sm.TelemetryMachine, src)
        assert (
            sm.advance(t, sm.TelemetryMachine, "swept") is DynamicAnalysisStatus.failed
        )
    # enriched is terminal, not sweepable.
    e = _Model(sm.TelemetryMachine, DynamicAnalysisStatus.enriched)
    with pytest.raises(sm.IllegalTransition):
        sm.advance(e, sm.TelemetryMachine, "swept")


# ── Issue ────────────────────────────────────────────────────────────────────


def test_issue_transitions() -> None:
    i = _Model(sm.IssueMachine, IssueStatus.open)
    assert sm.advance(i, sm.IssueMachine, "link_fix") is IssueStatus.fix_in_progress
    assert sm.advance(i, sm.IssueMachine, "resolve") is IssueStatus.resolved
    assert sm.advance(i, sm.IssueMachine, "recur") is IssueStatus.open


def test_issue_cannot_link_fix_when_resolved() -> None:
    i = _Model(sm.IssueMachine, IssueStatus.resolved)
    with pytest.raises(sm.IllegalTransition):
        sm.advance(i, sm.IssueMachine, "link_fix")


def test_issue_ignore_and_unignore() -> None:
    for src in (IssueStatus.open, IssueStatus.fix_in_progress):
        i = _Model(sm.IssueMachine, src)
        assert sm.advance(i, sm.IssueMachine, "ignore") is IssueStatus.ignored
        assert sm.advance(i, sm.IssueMachine, "unignore") is IssueStatus.open


def test_issue_cannot_ignore_when_resolved() -> None:
    i = _Model(sm.IssueMachine, IssueStatus.resolved)
    with pytest.raises(sm.IllegalTransition):
        sm.advance(i, sm.IssueMachine, "ignore")
