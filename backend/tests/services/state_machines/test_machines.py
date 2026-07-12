"""Behavioural tests for the four lifecycle state machines."""

import pytest

from app.models.enums import (
    AnalysisStatus,
    FixStatus,
    IssueStatus,
    PullRequestState,
    SSESignal,
)
from app.services.state_machines import (
    AnalysisEvent,
    FixEvent,
    IssueEvent,
    PullRequestEvent,
    analysis_machine,
    fix_machine,
    issue_machine,
    pull_request_machine,
)
from app.services.state_machines.base import IllegalTransition, StateMachine

ALL_MACHINES = [
    analysis_machine,
    fix_machine,
    issue_machine,
    pull_request_machine,
]


# ── Structural invariants shared by every machine ────────────────────────────


@pytest.mark.parametrize("machine", ALL_MACHINES, ids=lambda m: m.name)
def test_states_and_events_belong_to_declared_enums(machine: StateMachine) -> None:
    for t in machine.transitions:
        assert isinstance(t.event, machine.event_enum)
        assert t.dest in machine.state_enum
        for src in t.sources:
            assert src in machine.state_enum


@pytest.mark.parametrize("machine", ALL_MACHINES, ids=lambda m: m.name)
def test_initial_and_terminal_states_are_valid(machine: StateMachine) -> None:
    assert machine.initial_states <= set(machine.state_enum)
    assert machine.terminal_states <= set(machine.state_enum)


@pytest.mark.parametrize("machine", ALL_MACHINES, ids=lambda m: m.name)
def test_every_referenced_state_is_reachable(machine: StateMachine) -> None:
    # Every state the machine can be in (a transition source, or a declared
    # terminal/resting state) must be arrivable: either an initial state or the
    # destination of some transition. Catches orphaned states without assuming
    # terminals are absorbing (these lifecycles are intentionally re-entrant —
    # e.g. a resolved issue can recur, a rejected fix can be restored).
    reachable = set(machine.initial_states) | {t.dest for t in machine.transitions}
    referenced = {src for t in machine.transitions for src in t.sources}
    referenced |= machine.terminal_states
    orphans = referenced - reachable
    assert not orphans, f"{machine.name}: unreachable states {orphans}"


@pytest.mark.parametrize("machine", ALL_MACHINES, ids=lambda m: m.name)
def test_declared_outputs_are_sse_signals(machine: StateMachine) -> None:
    for t in machine.transitions:
        assert t.output is None or isinstance(t.output, SSESignal)


# ── Analysis ─────────────────────────────────────────────────────────────────


def test_analysis_happy_path() -> None:
    assert (
        analysis_machine.next_state(AnalysisStatus.running, AnalysisEvent.opa_succeeded)
        is AnalysisStatus.completed
    )
    assert (
        analysis_machine.output_for(AnalysisStatus.running, AnalysisEvent.opa_succeeded)
        is SSESignal.analysis_completed
    )


def test_analysis_sweep_from_pending_or_running() -> None:
    for src in (AnalysisStatus.pending, AnalysisStatus.running):
        assert (
            analysis_machine.next_state(src, AnalysisEvent.swept)
            is AnalysisStatus.failed
        )


def test_analysis_cannot_complete_from_terminal() -> None:
    with pytest.raises(IllegalTransition):
        analysis_machine.next_state(
            AnalysisStatus.completed, AnalysisEvent.opa_succeeded
        )


# ── Fix ──────────────────────────────────────────────────────────────────────


def test_fix_generation_and_delivery_path() -> None:
    state = FixStatus.pending
    for event, expected in [
        (FixEvent.start_generation, FixStatus.generating),
        (FixEvent.generation_succeeded, FixStatus.ready),
        (FixEvent.start_delivery, FixStatus.delivering),
        (FixEvent.delivery_succeeded, FixStatus.delivered),
    ]:
        state = fix_machine.next_state(state, event)
        assert state is expected


def test_fix_user_reject_is_idempotent() -> None:
    # reject is legal from every non-in-flight state, including rejected itself.
    for src in (FixStatus.ready, FixStatus.delivered, FixStatus.rejected):
        assert fix_machine.next_state(src, FixEvent.reject) is FixStatus.rejected


def test_fix_guard_reject_only_from_ready() -> None:
    assert (
        fix_machine.next_state(FixStatus.ready, FixEvent.supersede_closed_pr)
        is FixStatus.rejected
    )
    with pytest.raises(IllegalTransition):
        fix_machine.next_state(FixStatus.delivered, FixEvent.supersede_closed_pr)


def test_fix_restore_from_rejected() -> None:
    assert (
        fix_machine.next_state(FixStatus.rejected, FixEvent.restore) is FixStatus.ready
    )


def test_fix_force_start_delivery_from_non_ready() -> None:
    class _F:
        status = FixStatus.delivered

    f = _F()
    # Normal trigger is illegal from delivered; force bypasses the source check.
    with pytest.raises(IllegalTransition):
        fix_machine.trigger(f, FixEvent.start_delivery)
    fix_machine.force(f, FixEvent.start_delivery)
    assert f.status is FixStatus.delivering


def test_fix_sweep_from_in_flight_only() -> None:
    for src in (FixStatus.pending, FixStatus.generating, FixStatus.delivering):
        assert fix_machine.next_state(src, FixEvent.swept) is FixStatus.failed
    with pytest.raises(IllegalTransition):
        fix_machine.next_state(FixStatus.ready, FixEvent.swept)


# ── Pull request ─────────────────────────────────────────────────────────────


def test_pull_request_lifecycle() -> None:
    assert (
        pull_request_machine.next_state(PullRequestState.open, PullRequestEvent.close)
        is PullRequestState.closed
    )
    assert (
        pull_request_machine.next_state(
            PullRequestState.closed, PullRequestEvent.reopen
        )
        is PullRequestState.open
    )
    assert (
        pull_request_machine.next_state(PullRequestState.open, PullRequestEvent.merge)
        is PullRequestState.merged
    )


def test_pull_request_reopen_from_open_is_noop_via_try_trigger() -> None:
    class _PR:
        pr_state = PullRequestState.open

    pr = _PR()
    assert pull_request_machine.try_trigger(pr, PullRequestEvent.reopen) is False
    assert pr.pr_state is PullRequestState.open


def test_pull_request_cannot_reopen_a_merged_pr() -> None:
    with pytest.raises(IllegalTransition):
        pull_request_machine.next_state(
            PullRequestState.merged, PullRequestEvent.reopen
        )


# ── Issue (derived) ──────────────────────────────────────────────────────────


def test_issue_transitions() -> None:
    assert (
        issue_machine.next_state(IssueStatus.open, IssueEvent.link_fix)
        is IssueStatus.fix_in_progress
    )
    assert (
        issue_machine.next_state(IssueStatus.fix_in_progress, IssueEvent.resolve)
        is IssueStatus.resolved
    )
    assert (
        issue_machine.next_state(IssueStatus.resolved, IssueEvent.recur)
        is IssueStatus.open
    )


def test_issue_cannot_link_fix_when_resolved() -> None:
    with pytest.raises(IllegalTransition):
        issue_machine.next_state(IssueStatus.resolved, IssueEvent.link_fix)
