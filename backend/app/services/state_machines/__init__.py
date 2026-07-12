"""Formal state machines for the four GreenSecOps lifecycles.

Built on ``python-statemachine``. Each machine declares its states (the existing
status enums), its input events, the legal transitions between them, and — via
``outputs`` — the SSE signal each transition emits. They are the single source
of truth for the diagrams in ``docs/state-machines.md`` and are enforced at the
call sites that mutate persisted status through the helpers in :mod:`.base`.

Typical use::

    from app.services import state_machines as sm

    sm.advance(fix, sm.FixMachine, "start_generation")       # raises if illegal
    sm.try_advance(pr, sm.PullRequestMachine, "reopen")      # idempotent no-op
    sm.force_to(fix, sm.FixMachine, FixStatus.delivering)    # admin override
"""

from .analysis import AnalysisMachine
from .base import (
    IllegalTransition,
    advance,
    force_to,
    output_for,
    try_advance,
)
from .fix import IN_FLIGHT_STATUSES, FixMachine
from .issue import IssueMachine
from .pull_request import PullRequestMachine

__all__ = [
    # helpers
    "advance",
    "try_advance",
    "force_to",
    "output_for",
    "IllegalTransition",
    # machines
    "AnalysisMachine",
    "FixMachine",
    "IssueMachine",
    "PullRequestMachine",
    "IN_FLIGHT_STATUSES",
]
