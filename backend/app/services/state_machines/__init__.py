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

One lifecycle here is *derived* rather than persisted: :mod:`.engine_target`
folds a target's scan and fix statuses into a :class:`~app.models.enums.
TargetActivity` and says which :class:`~app.models.enums.TargetAction` that
forbids. It has no state column and so no ``StateMachine`` subclass, but it is
the graph the engine pages' buttons obey::

    sm.blocked_reason(sm.activity_of(scans, fixes), TargetAction.generate)
"""

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
from .engine_target import (
    ACTIVE_SCAN_STATUSES,
    BLOCKS,
    REASONS,
    activity_of,
    blocked_reason,
)
from .finding import FindingMachine
from .fix import (
    DELIVERED_FIX_STATUSES,
    IN_FLIGHT_STATUSES,
    REJECTED_STATUSES,
    FixMachine,
)
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
    # derived target activity
    "activity_of",
    "blocked_reason",
    "ACTIVE_SCAN_STATUSES",
    "BLOCKS",
    "REASONS",
    # machines
    "BillingSubscriptionMachine",
    "CloudAccountMachine",
    "FindingMachine",
    "FixMachine",
    "PullRequestMachine",
    "RepositoryMachine",
    "ScanMachine",
    "TelemetryMachine",
    "ENTITLED_STATUSES",
    "IN_FLIGHT_STATUSES",
    "REJECTED_STATUSES",
    "DELIVERED_FIX_STATUSES",
]
