"""Tests for the state-machine call-site helpers (advance / try_advance / force)."""

import pytest

from app.models.enums import FixStatus, PullRequestState
from app.services import state_machines as sm


class _Fix:
    def __init__(self, status: FixStatus) -> None:
        self.status = status


class _PR:
    def __init__(self, pr_state: PullRequestState | None) -> None:
        self.pr_state = pr_state


def test_advance_mutates_and_returns_new_state() -> None:
    fix = _Fix(FixStatus.pending)
    result = sm.advance(fix, sm.FixMachine, "start_generation")
    assert result is FixStatus.generating
    assert fix.status is FixStatus.generating


def test_advance_illegal_raises_and_does_not_mutate() -> None:
    fix = _Fix(FixStatus.delivered)
    with pytest.raises(sm.IllegalTransition):
        sm.advance(fix, sm.FixMachine, "start_generation")
    assert fix.status is FixStatus.delivered


def test_advance_on_null_state_raises() -> None:
    pr = _PR(None)
    with pytest.raises(sm.IllegalTransition):
        sm.advance(pr, sm.PullRequestMachine, "merge")
    assert pr.pr_state is None


def test_try_advance_fires_when_legal() -> None:
    pr = _PR(PullRequestState.open)
    assert sm.try_advance(pr, sm.PullRequestMachine, "merge") is True
    assert pr.pr_state is PullRequestState.merged


def test_try_advance_noops_when_illegal() -> None:
    pr = _PR(PullRequestState.merged)
    assert sm.try_advance(pr, sm.PullRequestMachine, "reopen") is False
    assert pr.pr_state is PullRequestState.merged


def test_try_advance_leaves_null_row_untouched() -> None:
    pr = _PR(None)
    assert sm.try_advance(pr, sm.PullRequestMachine, "merge") is False
    # The library must not auto-initialise a NULL legacy row to the initial state.
    assert pr.pr_state is None


def test_force_to_bypasses_source_guard() -> None:
    fix = _Fix(FixStatus.delivered)  # start_delivery is illegal from delivered
    sm.force_to(fix, sm.FixMachine, FixStatus.delivering)
    assert fix.status is FixStatus.delivering


def test_output_for_returns_declared_signal() -> None:
    from app.models.enums import SSESignal

    assert sm.output_for(sm.FixMachine, "generation_succeeded") is SSESignal.fix_ready
    assert sm.output_for(sm.FixMachine, "mark_ready") is None
