"""Behavioural tests for the four lifecycle state machines."""

import pytest
from statemachine import StateMachine

from app.models.enums import (
    AnalysisStatus,
    FixStatus,
    IssueStatus,
    PullRequestState,
    SSESignal,
)
from app.services import state_machines as sm

ALL_MACHINES = [
    sm.AnalysisMachine,
    sm.FixMachine,
    sm.PullRequestMachine,
    sm.IssueMachine,
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
    a = _Model(sm.AnalysisMachine, AnalysisStatus.running)
    assert (
        sm.advance(a, sm.AnalysisMachine, "opa_succeeded") is AnalysisStatus.completed
    )


def test_analysis_no_workflows_edge() -> None:
    a = _Model(sm.AnalysisMachine, AnalysisStatus.running)
    assert (
        sm.advance(a, sm.AnalysisMachine, "no_workflows_found")
        is AnalysisStatus.no_workflows
    )


def test_analysis_sweep_from_running() -> None:
    a = _Model(sm.AnalysisMachine, AnalysisStatus.running)
    assert sm.advance(a, sm.AnalysisMachine, "swept") is AnalysisStatus.failed


def test_analysis_cannot_advance_from_terminal() -> None:
    a = _Model(sm.AnalysisMachine, AnalysisStatus.completed)
    with pytest.raises(sm.IllegalTransition):
        sm.advance(a, sm.AnalysisMachine, "opa_succeeded")


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
    ):
        f = _Model(sm.FixMachine, src)
        assert sm.advance(f, sm.FixMachine, "reject") is FixStatus.rejected_by_user


def test_fix_reject_is_terminal_double_reject_is_illegal() -> None:
    # rejected_by_user is a true final state; the DELETE route makes a repeated
    # reject idempotent via try_advance, not a machine self-loop.
    f = _Model(sm.FixMachine, FixStatus.rejected_by_user)
    with pytest.raises(sm.IllegalTransition):
        sm.advance(f, sm.FixMachine, "reject")


def test_fix_guard_supersede_only_from_ready() -> None:
    f = _Model(sm.FixMachine, FixStatus.ready)
    assert (
        sm.advance(f, sm.FixMachine, "supersede_closed_pr")
        is FixStatus.superseded_by_closed_pr
    )
    f2 = _Model(sm.FixMachine, FixStatus.delivered)
    with pytest.raises(sm.IllegalTransition):
        sm.advance(f2, sm.FixMachine, "supersede_closed_pr")


def test_fix_restore_only_from_superseded_not_user_rejected() -> None:
    f = _Model(sm.FixMachine, FixStatus.superseded_by_closed_pr)
    assert sm.advance(f, sm.FixMachine, "restore") is FixStatus.ready
    # A user rejection is final — reopening a PR must not resurrect it.
    f2 = _Model(sm.FixMachine, FixStatus.rejected_by_user)
    with pytest.raises(sm.IllegalTransition):
        sm.advance(f2, sm.FixMachine, "restore")


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
