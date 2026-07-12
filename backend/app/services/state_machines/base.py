"""A small, dependency-free state-machine primitive.

The four GreenSecOps lifecycles (analysis, issue, fix, pull request) are each
declared as a :class:`StateMachine`: an explicit set of :class:`Transition`
records that name the **input event** driving them, the **source states** the
event is legal from, the **destination state**, and the **output** side effect
(the SSE signal the application emits when the transition fires).

The machine is the single source of truth for "what may follow what". Call
sites mutate persisted status by asking the machine for the next state
(:meth:`StateMachine.trigger`), so an illegal transition raises
:class:`IllegalTransition` instead of silently corrupting state.

This mirrors, in code, the diagrams in ``docs/state-machines.md``; a test
asserts the two stay in sync.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, TypeVar

from app.models.enums import SSESignal

S = TypeVar("S", bound=Enum)  # state enum
E = TypeVar("E", bound=Enum)  # input-event enum


class IllegalTransition(Exception):
    """Raised when an event is fired from a state that does not allow it."""

    def __init__(self, machine: str, current: Enum, event: Enum) -> None:
        self.machine = machine
        self.current = current
        self.event = event
        super().__init__(
            f"{machine}: event {event.value!r} is not allowed from state "
            f"{current.value!r}"
        )


@dataclass(frozen=True)
class Transition(Generic[S, E]):
    """One edge of a state machine.

    Attributes:
        event: the input that triggers this edge.
        sources: states the event is legal from.
        dest: the resulting state.
        output: the SSE signal emitted as the transition's observable output
            (``None`` for internal transitions with no notification).
        guard: human-readable precondition enforced by the caller, for docs.
        description: what the transition represents.
    """

    event: E
    sources: frozenset[S]
    dest: S
    output: SSESignal | None = None
    guard: str | None = None
    description: str = ""


@dataclass(frozen=True)
class StateMachine(Generic[S, E]):
    """An immutable collection of transitions over a state enum.

    ``state_attr`` is the attribute the machine reads and writes on a model
    instance (``"status"`` for analysis/fix, ``"pr_state"`` for pull request).
    ``initial_states`` and ``terminal_states`` are declarative — recorded for
    documentation and validated by tests, not enforced at runtime.
    """

    name: str
    state_attr: str
    state_enum: type[S]
    event_enum: type[E]
    transitions: tuple[Transition[S, E], ...]
    initial_states: frozenset[S]
    terminal_states: frozenset[S]
    _index: dict[tuple[S, E], Transition[S, E]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        for t in self.transitions:
            for src in t.sources:
                key = (src, t.event)
                if key in self._index:
                    raise ValueError(
                        f"{self.name}: duplicate transition for "
                        f"({src.value!r}, {t.event.value!r})"
                    )
                self._index[key] = t

    # ── Queries ──────────────────────────────────────────────────────────────

    def can(self, current: S, event: E) -> bool:
        """True when ``event`` is legal from ``current``."""
        return (current, event) in self._index

    def next_state(self, current: S, event: E) -> S:
        """Destination state for ``event`` from ``current`` (validates)."""
        transition = self._index.get((current, event))
        if transition is None:
            raise IllegalTransition(self.name, current, event)
        return transition.dest

    def output_for(self, current: S, event: E) -> SSESignal | None:
        """The SSE signal declared as this transition's output."""
        transition = self._index.get((current, event))
        if transition is None:
            raise IllegalTransition(self.name, current, event)
        return transition.output

    def allowed_events(self, current: S) -> set[E]:
        """Every event legal from ``current``."""
        return {event for (state, event) in self._index if state == current}

    def event_dest(self, event: E) -> S:
        """The single destination state ``event`` always leads to.

        Raises ``ValueError`` if the event is unknown or (in some other
        machine) maps to more than one destination.
        """
        dests = {t.dest for t in self.transitions if t.event == event}
        if len(dests) != 1:
            raise ValueError(
                f"{self.name}: event {event.value!r} has {len(dests)} "
                "destinations; event_dest requires exactly one"
            )
        return next(iter(dests))

    # ── Mutation ─────────────────────────────────────────────────────────────

    def trigger(self, obj: object, event: E) -> S:
        """Advance ``obj``'s state by firing ``event``; returns the new state.

        Reads and writes ``obj.<state_attr>``. Raises
        :class:`IllegalTransition` (without mutating) when the event is not
        legal from the current state.
        """
        current: S = getattr(obj, self.state_attr)
        dest = self.next_state(current, event)
        setattr(obj, self.state_attr, dest)
        return dest

    def try_trigger(self, obj: object, event: E) -> bool:
        """Fire ``event`` if legal from the current state; else no-op.

        Returns whether the transition fired. Use at boundaries where
        duplicate or out-of-order inputs are expected (webhooks, missed-event
        reconciliation) and must not raise.
        """
        current: S = getattr(obj, self.state_attr)
        if not self.can(current, event):
            return False
        setattr(obj, self.state_attr, self.next_state(current, event))
        return True

    def force(self, obj: object, event: E) -> S:
        """Set the state to ``event``'s destination, bypassing source checks.

        For explicit administrator overrides (e.g. forced fix delivery) that
        intentionally short-circuit the normal guards, while still expressing
        the change in the machine's own vocabulary.
        """
        dest = self.event_dest(event)
        setattr(obj, self.state_attr, dest)
        return dest

    def apply(self, obj: object, event: E, *, force: bool = False) -> S:
        """:meth:`force` when ``force`` else :meth:`trigger`."""
        return self.force(obj, event) if force else self.trigger(obj, event)
