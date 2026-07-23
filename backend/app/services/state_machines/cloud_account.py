"""Cloud account connection lifecycle state machine (``python-statemachine``).

States mirror ``CloudAccountStatus``. Tracks the AssumeRole+ExternalId
connection wizard: a newly created ``CloudAccount`` starts unverified, the
"Test connection" flow (or the next scheduled scan) verifies or fails it, and
an admin can disable/re-enable it. ``enable`` sends a disabled account back to
``pending_verification`` rather than straight to ``connected`` — the role
trust policy or permissions may have changed while it sat disabled, so a scan
should not resume on stale trust.

Behaviour lands with the cloud-account connect/verify API routes (a later
phase); this machine is the declared, testable graph they advance against.
"""

from __future__ import annotations

from statemachine import State, StateMachine

from app.models.enums import CloudAccountStatus


class CloudAccountMachine(StateMachine):
    state_field = "status"

    pending_verification = State(
        initial=True, value=CloudAccountStatus.pending_verification
    )
    connected = State(value=CloudAccountStatus.connected)
    error = State(value=CloudAccountStatus.error)
    disabled = State(value=CloudAccountStatus.disabled)

    # Inputs (events)
    verify = pending_verification.to(connected) | error.to(connected)
    verification_failed = pending_verification.to(error) | connected.to(error)
    disable = (
        pending_verification.to(disabled) | connected.to(disabled) | error.to(disabled)
    )
    enable = disabled.to(pending_verification)  # re-verify before scans resume

    # No SSE wiring yet — same rationale as ScanMachine.
    outputs: dict[str, None] = {
        "verify": None,
        "verification_failed": None,
        "disable": None,
        "enable": None,
    }
