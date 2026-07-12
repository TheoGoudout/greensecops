"""Shared helpers for the lifecycle state machines.

Each lifecycle is a :class:`statemachine.StateMachine` subclass (the
``python-statemachine`` library) that binds to a persisted model instance and
stores its state in a column (``status`` or ``pr_state``). The library is the
engine: it owns the state graph and rejects illegal transitions. On top of it
these helpers add the three call-site ergonomics the application needs:

* :func:`advance` — fire an event, raising on an illegal transition (normal
  worker/API paths).
* :func:`try_advance` — fire an event only if legal, else no-op (idempotent
  boundaries where GitHub may redeliver or reorder events).
* :func:`force_to` — set the state directly, bypassing the source guard, for
  explicit administrator overrides (forced fix delivery).

Concrete machines declare two extra class attributes: ``state_field`` (the
model column they drive) and ``outputs`` (a mapping of event name → the
``SSESignal`` emitted as that transition's observable output).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from statemachine import StateMachine
from statemachine.exceptions import (
    InvalidStateValue,
    TransitionNotAllowed,
)

if TYPE_CHECKING:
    from app.models.enums import SSESignal


class IllegalTransition(Exception):
    """Raised by :func:`advance` when an event is not legal from the current
    state (or the state column is ``NULL``). Wraps the library's
    ``TransitionNotAllowed`` so call sites depend on this package, not the
    library directly.
    """


def _state_field(machine_cls: type[StateMachine]) -> str:
    # getattr (not attribute access): mypy cannot see the subclass-only
    # ``state_field`` attribute on the ``type[StateMachine]`` base.
    return cast(str, getattr(machine_cls, "state_field"))  # noqa: B009


def _current(model: object, machine_cls: type[StateMachine]) -> object:
    return getattr(model, _state_field(machine_cls))


def advance(model: object, machine_cls: type[StateMachine], event: str) -> object:
    """Fire ``event`` on ``model`` via ``machine_cls``; return the new state.

    Raises :class:`IllegalTransition` (without mutating) when the event is not
    legal from the model's current state.
    """
    field = _state_field(machine_cls)
    if _current(model, machine_cls) is None:
        raise IllegalTransition(
            f"{machine_cls.__name__}: cannot fire {event!r} on a row whose "
            f"{field!r} is NULL"
        )
    machine = machine_cls(model, state_field=field)
    try:
        machine.send(event)
    except TransitionNotAllowed as exc:
        raise IllegalTransition(
            f"{machine_cls.__name__}: {event!r} is not allowed from "
            f"{_current(model, machine_cls)!r}"
        ) from exc
    return _current(model, machine_cls)


def try_advance(model: object, machine_cls: type[StateMachine], event: str) -> bool:
    """Fire ``event`` if legal from the current state; else no-op.

    Returns whether the transition fired. A model whose state column is
    ``NULL``/unknown (legacy rows) is treated as "cannot transition" and is left
    untouched — binding is skipped so the library does not auto-initialise it.
    """
    if _current(model, machine_cls) is None:
        return False
    try:
        machine = machine_cls(model, state_field=_state_field(machine_cls))
    except InvalidStateValue:
        return False
    try:
        machine.send(event)
        return True
    except TransitionNotAllowed:
        return False


def force_to(model: object, machine_cls: type[StateMachine], state: object) -> None:
    """Set ``model``'s state column directly, bypassing the source guard.

    For explicit administrator overrides (e.g. forced fix delivery) that
    intentionally short-circuit the normal transition guards.
    """
    setattr(model, _state_field(machine_cls), state)


def output_for(machine_cls: type[StateMachine], event: str) -> SSESignal | None:
    """The SSE signal declared as ``event``'s observable output, if any."""
    outputs = cast("dict[str, SSESignal | None]", getattr(machine_cls, "outputs"))  # noqa: B009
    return outputs.get(event)
