"""Billing: plans, metering, quota enforcement, and the subscription lifecycle.

Layered so that nothing below depends on anything above it:

``owner``
    Which user an org's usage is charged to.
``usage``
    The append-only ledger — what was consumed, when, and by which engine.
``lifecycle``
    Billing periods, entitlement (``effective_tier``), and state transitions.
``quota``
    Reads the ledger against the plan catalog and decides what may run.
``errors``
    The structured 402/503 payloads every refusal leaves through.
``stripe_gateway``
    The only module that talks to Stripe.

The plan catalog itself lives in ``app.core.plans`` — it is configuration that
the marketing site's codegen also reads, so it sits below the service layer.
"""

from . import errors, lifecycle, owner, quota, stripe_gateway, usage

__all__ = [
    "errors",
    "lifecycle",
    "owner",
    "quota",
    "stripe_gateway",
    "usage",
]
