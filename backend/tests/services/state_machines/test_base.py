"""Unit tests for the state-machine primitive."""

import enum

import pytest

from app.models.enums import SSESignal
from app.services.state_machines.base import (
    IllegalTransition,
    StateMachine,
    Transition,
)


class _State(str, enum.Enum):
    a = "a"
    b = "b"
    c = "c"


class _Event(str, enum.Enum):
    go = "go"
    back = "back"
    finish = "finish"


def _machine() -> StateMachine[_State, _Event]:
    return StateMachine(
        name="demo",
        state_attr="status",
        state_enum=_State,
        event_enum=_Event,
        transitions=(
            Transition(
                event=_Event.go,
                sources=frozenset({_State.a}),
                dest=_State.b,
                output=SSESignal.analysis_started,
            ),
            Transition(event=_Event.back, sources=frozenset({_State.b}), dest=_State.a),
            Transition(
                event=_Event.finish,
                sources=frozenset({_State.a, _State.b}),
                dest=_State.c,
            ),
        ),
        initial_states=frozenset({_State.a}),
        terminal_states=frozenset({_State.c}),
    )


class _Obj:
    def __init__(self, status: _State) -> None:
        self.status = status


def test_can_and_next_state() -> None:
    m = _machine()
    assert m.can(_State.a, _Event.go)
    assert not m.can(_State.c, _Event.go)
    assert m.next_state(_State.a, _Event.go) is _State.b


def test_next_state_illegal_raises() -> None:
    m = _machine()
    with pytest.raises(IllegalTransition) as exc:
        m.next_state(_State.c, _Event.go)
    assert exc.value.current is _State.c
    assert exc.value.event is _Event.go


def test_allowed_events() -> None:
    m = _machine()
    assert m.allowed_events(_State.a) == {_Event.go, _Event.finish}
    assert m.allowed_events(_State.c) == set()


def test_output_for() -> None:
    m = _machine()
    assert m.output_for(_State.a, _Event.go) is SSESignal.analysis_started
    assert m.output_for(_State.b, _Event.back) is None


def test_event_dest_single() -> None:
    m = _machine()
    assert m.event_dest(_Event.finish) is _State.c


def test_trigger_mutates_object() -> None:
    m = _machine()
    obj = _Obj(_State.a)
    assert m.trigger(obj, _Event.go) is _State.b
    assert obj.status is _State.b


def test_trigger_illegal_does_not_mutate() -> None:
    m = _machine()
    obj = _Obj(_State.c)
    with pytest.raises(IllegalTransition):
        m.trigger(obj, _Event.go)
    assert obj.status is _State.c


def test_try_trigger_returns_false_and_noops_when_illegal() -> None:
    m = _machine()
    obj = _Obj(_State.c)
    assert m.try_trigger(obj, _Event.go) is False
    assert obj.status is _State.c


def test_try_trigger_fires_when_legal() -> None:
    m = _machine()
    obj = _Obj(_State.a)
    assert m.try_trigger(obj, _Event.go) is True
    assert obj.status is _State.b


def test_force_bypasses_source_check() -> None:
    m = _machine()
    obj = _Obj(_State.c)  # `go` is illegal from c
    assert m.force(obj, _Event.go) is _State.b
    assert obj.status is _State.b


def test_apply_dispatches_on_force_flag() -> None:
    m = _machine()
    forced = _Obj(_State.c)
    m.apply(forced, _Event.go, force=True)
    assert forced.status is _State.b

    normal = _Obj(_State.a)
    m.apply(normal, _Event.go, force=False)
    assert normal.status is _State.b


def test_duplicate_transition_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate transition"):
        StateMachine(
            name="dup",
            state_attr="status",
            state_enum=_State,
            event_enum=_Event,
            transitions=(
                Transition(_Event.go, frozenset({_State.a}), _State.b),
                Transition(_Event.go, frozenset({_State.a}), _State.c),
            ),
            initial_states=frozenset({_State.a}),
            terminal_states=frozenset({_State.c}),
        )
