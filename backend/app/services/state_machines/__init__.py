"""Formal state machines for GreenSecOps's persisted lifecycles.

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
from .billing import (
    ENTITLED_STATUSES,
    BillingSubscriptionMachine,
)
from .cloud_account import CloudAccountMachine
from .finding import FindingMachine
from .fix import (
    DELIVERED_FIX_STATUSES,
    IN_FLIGHT_STATUSES,
    REJECTED_STATUSES,
    FixMachine,
)
from .issue import IssueMachine
from .pull_request import PullRequestMachine
from .repository import RepositoryMachine, sync_access_flag
from .scan import ScanMachine
from .telemetry import TelemetryMachine

__all__ = [
    # helpers
    "advance",
    "try_advance",
    "force_to",
    "output_for",
    "IllegalTransition",
    "sync_access_flag",
    # machines
    "AnalysisMachine",
    "BillingSubscriptionMachine",
    "CloudAccountMachine",
    "FindingMachine",
    "FixMachine",
    "IssueMachine",
    "PullRequestMachine",
    "RepositoryMachine",
    "ScanMachine",
    "TelemetryMachine",
    "ENTITLED_STATUSES",
    "IN_FLIGHT_STATUSES",
    "REJECTED_STATUSES",
    "DELIVERED_FIX_STATUSES",
]
