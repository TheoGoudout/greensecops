"""Formal state machines for the four GreenSecOps lifecycles.

Each machine declares its states (the existing status enums), its input events,
the legal transitions between states, and the SSE output each transition emits.
They are the single source of truth for the diagrams in
``docs/state-machines.md`` and are enforced at the call sites that mutate
persisted status.
"""

from .analysis import AnalysisEvent, analysis_machine
from .base import IllegalTransition, StateMachine, Transition
from .fix import IN_FLIGHT_STATUSES, FixEvent, fix_machine
from .issue import IssueEvent, issue_machine
from .pull_request import PullRequestEvent, pull_request_machine

__all__ = [
    "StateMachine",
    "Transition",
    "IllegalTransition",
    "analysis_machine",
    "AnalysisEvent",
    "fix_machine",
    "FixEvent",
    "IN_FLIGHT_STATUSES",
    "issue_machine",
    "IssueEvent",
    "pull_request_machine",
    "PullRequestEvent",
]
