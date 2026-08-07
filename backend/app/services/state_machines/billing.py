"""Billing subscription lifecycle state machine (``python-statemachine``).

States mirror ``SubscriptionStatus``. This is the *payment* lifecycle, not the
plan: ``UserTier`` says what was bought and never changes on its own, while
these states say whether it is currently being paid for. Only
``services/billing/lifecycle.effective_tier`` combines the two, and only
quota enforcement reads the result.

The shape worth understanding is the grace window. A failed payment moves
``active -> past_due`` and **nothing else happens**: the account keeps its full
paid limits while the dunning task emails reminders. Only when the window
closes does ``grace_expired`` move it to ``unpaid``, which is the first state
that actually costs the user anything (Free limits — no data is ever removed).
Paying at any point in either state returns the subscription to ``active``.

``incomplete`` is the initial state because it is the genuine "nothing has been
paid yet" state a Checkout-created subscription starts in. Accounts that never
bought anything are created directly as ``active`` on the free tier via the
column default — there is nothing to collect from them, so there is nothing to
be incomplete about.

Behaviour lives in ``services/billing/lifecycle.py`` (transitions),
``api/routes/billing.py`` (the Stripe webhook) and
``workers/tasks/billing.py`` (dunning and grace expiry).
"""

from __future__ import annotations

from statemachine import State, StateMachine

from app.models.enums import SSESignal, SubscriptionStatus


class BillingSubscriptionMachine(StateMachine):
    state_field = "status"

    incomplete = State(initial=True, value=SubscriptionStatus.incomplete)
    trialing = State(value=SubscriptionStatus.trialing)
    active = State(value=SubscriptionStatus.active)
    past_due = State(value=SubscriptionStatus.past_due)
    unpaid = State(value=SubscriptionStatus.unpaid)
    pending_cancellation = State(value=SubscriptionStatus.pending_cancellation)
    canceled = State(value=SubscriptionStatus.canceled, final=True)

    # ─── Inputs (events) ──────────────────────────────────────────────────
    # Checkout finished and the first invoice was paid.
    checkout_completed = incomplete.to(active)
    # Checkout finished into a trial: no money has moved yet.
    trial_started = incomplete.to(trialing)
    trial_converted = trialing.to(active)
    # The trial ended and the first real charge failed — same grace treatment
    # as any other failed payment.
    trial_ended = trialing.to(past_due)

    payment_failed = active.to(past_due) | trialing.to(past_due)
    # Recovery from either side of the grace boundary. An ``unpaid`` account
    # that pays is restored in full, not left on Free until the next cycle.
    payment_succeeded = past_due.to(active) | unpaid.to(active)
    grace_expired = past_due.to(unpaid)

    # The user cancelled but is paid through the end of the period.
    cancel_requested = (
        active.to(pending_cancellation)
        | trialing.to(pending_cancellation)
        | past_due.to(pending_cancellation)
    )
    resumed = pending_cancellation.to(active)
    period_ended = pending_cancellation.to(canceled)

    # Stripe reports the subscription gone (deleted, or a checkout session that
    # expired before payment). Terminal from wherever it was.
    subscription_deleted = (
        incomplete.to(canceled)
        | trialing.to(canceled)
        | active.to(canceled)
        | past_due.to(canceled)
        | unpaid.to(canceled)
        | pending_cancellation.to(canceled)
    )

    # An upgrade or downgrade between paid tiers. The payment state is
    # unchanged — only ``BillingSubscription.tier`` moves — but it is modelled
    # as an event so the tier change emits an SSE signal like everything else.
    # ``to.itself`` is untyped in python-statemachine; the alternative is
    # dropping the self-loop and losing the SSE signal on a tier change.
    plan_changed = active.to.itself() | trialing.to.itself()  # type: ignore[no-untyped-call]

    # ─── Outputs (SSE signal emitted when each event fires) ───────────────
    outputs: dict[str, SSESignal | None] = {
        "checkout_completed": SSESignal.subscription_activated,
        "trial_started": SSESignal.subscription_updated,
        "trial_converted": SSESignal.subscription_activated,
        "trial_ended": SSESignal.subscription_past_due,
        "payment_failed": SSESignal.subscription_past_due,
        "payment_succeeded": SSESignal.subscription_activated,
        "grace_expired": SSESignal.subscription_unpaid,
        "cancel_requested": SSESignal.subscription_updated,
        "resumed": SSESignal.subscription_activated,
        "period_ended": SSESignal.subscription_canceled,
        "subscription_deleted": SSESignal.subscription_canceled,
        "plan_changed": SSESignal.subscription_updated,
    }


# States in which the purchased tier's limits still apply in full. Everything
# outside this set falls back to Free — see ``lifecycle.effective_tier``.
ENTITLED_STATUSES: frozenset[SubscriptionStatus] = frozenset(
    {
        SubscriptionStatus.trialing,
        SubscriptionStatus.active,
        # Grace: a failed payment does not immediately cost the user anything.
        SubscriptionStatus.past_due,
        # Cancelled but paid through the period end.
        SubscriptionStatus.pending_cancellation,
    }
)
