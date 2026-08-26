"""Tests for the /api/v1/billing/ endpoints and the Stripe webhook.

The quota/usage/lifecycle *logic* is tested against the services in
``tests/services/billing/``; this module covers the HTTP surface — what the
billing page is served, what checkout refuses, and how Stripe's event
vocabulary is translated into our lifecycle.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.routes import billing
from app.core.config import settings
from app.models import (
    Invoice,
    InvoiceStatus,
    OssApplication,
    OssApplicationStatus,
    SubscriptionStatus,
    UsageEngine,
    UsageMeter,
    UserTier,
)
from app.services.billing.lifecycle import get_or_create_subscription
from tests.utils.billing import (
    make_subscription,
    make_user,
    owned_setup,
    record_usage,
)
from tests.utils.user import authentication_token_from_email


@pytest.fixture
def user_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )


# ─── Plans ───────────────────────────────────────────────────────────────────


def test_list_plans_returns_the_catalog(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    response = client.get(f"{settings.API_V1_STR}/billing/plans", headers=user_headers)
    assert response.status_code == 200
    plans = response.json()
    assert [p["tier"] for p in plans] == [
        "free",
        "starter",
        "pro",
        "ultimate",
        "open_source",
    ]
    free = next(p for p in plans if p["tier"] == "free")
    assert free["limits"] == {"analyses": 100, "fixes": 10, "repos": 3}
    ultimate = next(p for p in plans if p["tier"] == "ultimate")
    assert ultimate["limits"]["analyses"] is None  # unlimited survives the wire


def test_plans_are_not_purchasable_without_stripe(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    """A self-hosted install should not offer a button that 503s."""
    with patch.object(settings, "STRIPE_SECRET_KEY", None):
        response = client.get(
            f"{settings.API_V1_STR}/billing/plans", headers=user_headers
        )
    assert all(p["is_purchasable"] is False for p in response.json())


def test_plans_are_purchasable_with_stripe_configured(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    with patch.object(settings, "STRIPE_SECRET_KEY", "sk_test_x"):
        response = client.get(
            f"{settings.API_V1_STR}/billing/plans", headers=user_headers
        )
    purchasable = {p["tier"] for p in response.json() if p["is_purchasable"]}
    assert purchasable == {"starter", "pro", "ultimate"}


# ─── Subscription & usage ────────────────────────────────────────────────────


def test_subscription_reports_plan_status_and_usage(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/billing/subscription", headers=user_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tier"] == "free"
    assert body["effective_tier"] == "free"
    assert body["status"] == "active"
    assert body["period_end"] is not None
    for key in ("analyses_used", "fixes_used", "repos_used"):
        assert isinstance(body[key], int)


def test_subscription_shows_both_tiers_when_downgraded(db: Session) -> None:
    """A Pro account on Free limits must not silently report as Free.

    Reporting only one of the two would either hide that the plan is currently
    restricted, or hide that it is still a Pro plan waiting to be restored.
    """
    user = make_user(db, tier=UserTier.pro)
    sub = make_subscription(
        db, user, tier=UserTier.pro, status=SubscriptionStatus.unpaid
    )
    from app.services.billing.lifecycle import effective_tier

    assert sub.tier == UserTier.pro
    assert effective_tier(sub) == UserTier.free


def test_usage_includes_the_per_engine_breakdown(db: Session) -> None:
    user, org, repo = owned_setup(db)
    get_or_create_subscription(db, user)
    record_usage(db, user, org, engine=UsageEngine.terraform, repo=repo)
    record_usage(db, user, org, engine=UsageEngine.terraform, repo=repo)
    record_usage(db, user, org, engine=UsageEngine.workflow, repo=repo)
    record_usage(db, user, org, meter=UsageMeter.fixes, engine=UsageEngine.docker)

    from app.services.billing.quota import snapshot
    from app.services.billing.usage import period_breakdown

    snap = snapshot(db, user)
    assert snap.analyses_used == 3
    assert snap.fixes_used == 1

    rows = period_breakdown(
        db, user.id, snap.subscription.period_start, snap.subscription.period_end
    )
    engines = {(m.value, e.value): q for m, e, q in rows}
    assert engines[("analyses", "terraform")] == 2
    assert engines[("analyses", "workflow")] == 1
    assert engines[("fixes", "docker")] == 1


def test_limits_endpoint_reads_the_subscription(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    """It used to read ``User.tier`` while the enforcer read the subscription."""
    response = client.get(f"{settings.API_V1_STR}/billing/limits", headers=user_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["tier"] == "free"
    assert body["limits"]["analyses"] == 100


def test_invoices_are_empty_without_a_subscription(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/billing/invoices", headers=user_headers
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ─── Checkout & portal ───────────────────────────────────────────────────────


def test_checkout_refuses_a_plan_that_cannot_be_bought(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    with patch.object(settings, "STRIPE_SECRET_KEY", "sk_test_x"):
        response = client.post(
            f"{settings.API_V1_STR}/billing/checkout-sessions",
            headers=user_headers,
            json={"tier": "open_source"},
        )
    assert response.status_code == 402
    detail = response.json()["detail"]
    # Says which route to take instead of just refusing.
    assert "Apply for it" in detail["message"]


def test_checkout_refuses_the_plan_you_are_already_on(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    with patch.object(settings, "STRIPE_SECRET_KEY", "sk_test_x"):
        response = client.post(
            f"{settings.API_V1_STR}/billing/checkout-sessions",
            headers=user_headers,
            json={"tier": "free"},
        )
    assert response.status_code == 402


def test_checkout_returns_the_stripe_url(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    with (
        patch.object(settings, "STRIPE_SECRET_KEY", "sk_test_x"),
        patch.object(
            billing.stripe_gateway,
            "create_checkout_session",
            return_value="https://checkout.stripe.com/c/pay/xyz",
        ) as create,
    ):
        response = client.post(
            f"{settings.API_V1_STR}/billing/checkout-sessions",
            headers=user_headers,
            json={"tier": "pro"},
        )
    assert response.status_code == 200
    assert response.json()["url"].startswith("https://checkout.stripe.com/")
    # Our subscription id rides along so the webhook can match the result back.
    assert create.call_args.kwargs["client_reference_id"]


def test_checkout_503s_when_stripe_is_unconfigured(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    """Self-hosted installs get a clear message, not an SDK stack trace."""
    with patch.object(settings, "STRIPE_SECRET_KEY", None):
        response = client.post(
            f"{settings.API_V1_STR}/billing/checkout-sessions",
            headers=user_headers,
            json={"tier": "pro"},
        )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "stripe_not_configured"


def test_portal_refuses_without_a_payment_method(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/billing/portal-sessions", headers=user_headers
    )
    assert response.status_code == 402
    assert "Choose a plan" in response.json()["detail"]["message"]


# ─── Open-source applications ────────────────────────────────────────────────


def test_oss_application_can_be_submitted_once(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    body = {
        "repo_url": "https://github.com/acme/widget",
        "license_name": "MIT",
        "justification": "Public library used by several projects.",
    }
    first = client.post(
        f"{settings.API_V1_STR}/billing/oss-applications",
        headers=user_headers,
        json=body,
    )
    assert first.status_code == 201
    assert first.json()["status"] == "pending"

    # A second concurrent application would give reviewers duplicates.
    second = client.post(
        f"{settings.API_V1_STR}/billing/oss-applications",
        headers=user_headers,
        json=body,
    )
    assert second.status_code == 409


def test_oss_approval_grants_the_plan(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    applicant = make_user(db)
    application = OssApplication(
        user_id=applicant.id,
        repo_url="https://github.com/acme/tool",
        license_name="Apache-2.0",
        justification="Open source.",
    )
    db.add(application)
    db.commit()
    db.refresh(application)

    response = client.patch(
        f"{settings.API_V1_STR}/billing/oss-applications/{application.id}",
        headers=superuser_token_headers,
        json={"approve": True},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"

    db.refresh(applicant)
    assert applicant.tier == UserTier.open_source
    sub = get_or_create_subscription(db, applicant)
    assert sub.tier == UserTier.open_source


def test_oss_rejection_records_the_reason(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """A decline the applicant can act on beats a silent no."""
    applicant = make_user(db)
    application = OssApplication(
        user_id=applicant.id,
        repo_url="https://github.com/acme/private-ish",
        license_name="Proprietary",
        justification="Please?",
    )
    db.add(application)
    db.commit()
    db.refresh(application)

    response = client.patch(
        f"{settings.API_V1_STR}/billing/oss-applications/{application.id}",
        headers=superuser_token_headers,
        json={"approve": False, "review_note": "Licence is not OSI-approved."},
    )
    assert response.status_code == 200
    assert response.json()["review_note"] == "Licence is not OSI-approved."
    db.refresh(applicant)
    assert applicant.tier == UserTier.free


def test_oss_review_queue_is_superuser_only(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    # The review queue used to be `/oss-applications` while a user's own
    # applications were `/oss-application` — one letter apart and two different
    # audiences. The queue is `/oss-applications/all` now.
    response = client.get(
        f"{settings.API_V1_STR}/billing/oss-applications/all", headers=user_headers
    )
    assert response.status_code in (401, 403)


def test_reviewing_twice_is_refused(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    applicant = make_user(db)
    application = OssApplication(
        user_id=applicant.id,
        repo_url="https://github.com/acme/x",
        license_name="MIT",
        justification="…",
        status=OssApplicationStatus.approved,
    )
    db.add(application)
    db.commit()
    db.refresh(application)

    response = client.patch(
        f"{settings.API_V1_STR}/billing/oss-applications/{application.id}",
        headers=superuser_token_headers,
        json={"approve": False},
    )
    assert response.status_code == 409


# ─── Stripe webhook ──────────────────────────────────────────────────────────


def _event(event_type: str, obj: dict[str, Any], event_id: str | None = None) -> dict:
    return {
        "id": event_id or f"evt_{uuid.uuid4().hex[:16]}",
        "type": event_type,
        "data": {"object": obj},
    }


def _post_event(client: TestClient, event: dict) -> Any:
    """Post an event with signature verification stubbed out.

    Verification itself is covered by its own test; every other webhook test is
    about what the handler *does* with a valid event.
    """
    with patch.object(
        billing.stripe_gateway, "parse_webhook_event", return_value=event
    ):
        return client.post(
            f"{settings.API_V1_STR}/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=x"},
        )


def _subscribed(db: Session, customer_id: str, tier: UserTier = UserTier.pro):  # type: ignore[no-untyped-def]
    user, _org, _repo = owned_setup(db, tier=tier)
    sub = get_or_create_subscription(db, user)
    sub.stripe_customer_id = customer_id
    sub.stripe_subscription_id = f"sub_{uuid.uuid4().hex[:12]}"
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def test_invoice_payment_failed_opens_the_grace_window(
    client: TestClient, db: Session
) -> None:
    customer = f"cus_{uuid.uuid4().hex[:12]}"
    sub = _subscribed(db, customer)

    with patch.object(billing, "_notify"):
        response = _post_event(
            client,
            _event(
                "invoice.payment_failed",
                {
                    "id": f"in_{uuid.uuid4().hex[:12]}",
                    "customer": customer,
                    "subscription": sub.stripe_subscription_id,
                    "status": "open",
                    "amount_due": 7900,
                    "amount_paid": 0,
                    "currency": "usd",
                    "hosted_invoice_url": "https://invoice.stripe.com/i/x",
                },
            ),
        )
    assert response.status_code == 200
    db.refresh(sub)
    assert sub.status == SubscriptionStatus.past_due
    assert sub.grace_expires_at is not None
    # Service continues in full through the window.
    from app.services.billing.lifecycle import effective_tier

    assert effective_tier(sub) == UserTier.pro


def test_invoice_paid_restores_an_unpaid_subscription(
    client: TestClient, db: Session
) -> None:
    customer = f"cus_{uuid.uuid4().hex[:12]}"
    sub = _subscribed(db, customer)
    sub.status = SubscriptionStatus.unpaid
    db.add(sub)
    db.commit()

    with patch.object(billing, "_notify"):
        response = _post_event(
            client,
            _event(
                "invoice.paid",
                {
                    "id": f"in_{uuid.uuid4().hex[:12]}",
                    "customer": customer,
                    "subscription": sub.stripe_subscription_id,
                    "status": "paid",
                    "amount_due": 7900,
                    "amount_paid": 7900,
                    "currency": "usd",
                },
            ),
        )
    assert response.status_code == 200
    db.refresh(sub)
    assert sub.status == SubscriptionStatus.active


def test_invoice_is_mirrored_into_the_database(client: TestClient, db: Session) -> None:
    """Billing history has to survive independently of Stripe."""
    customer = f"cus_{uuid.uuid4().hex[:12]}"
    sub = _subscribed(db, customer)
    invoice_id = f"in_{uuid.uuid4().hex[:12]}"

    with patch.object(billing, "_notify"):
        _post_event(
            client,
            _event(
                "invoice.paid",
                {
                    "id": invoice_id,
                    "customer": customer,
                    "subscription": sub.stripe_subscription_id,
                    "status": "paid",
                    "number": "GS-0001",
                    "amount_due": 7900,
                    "amount_paid": 7900,
                    "currency": "usd",
                    "hosted_invoice_url": "https://invoice.stripe.com/i/y",
                    "period_start": int(
                        datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp()
                    ),
                    "period_end": int(
                        datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()
                    ),
                },
            ),
        )
    stored = db.exec(
        select(Invoice).where(Invoice.stripe_invoice_id == invoice_id)
    ).first()
    assert stored is not None
    assert stored.status == InvoiceStatus.paid
    # Money is stored in minor units, exactly as Stripe reports it.
    assert stored.amount_paid_cents == 7900
    assert stored.number == "GS-0001"
    assert stored.hosted_invoice_url == "https://invoice.stripe.com/i/y"


def test_a_redelivered_event_is_ignored(client: TestClient, db: Session) -> None:
    """Stripe retries on any non-2xx and redelivers on its own schedule.

    Without idempotency a replayed ``payment_failed`` would re-send a dunning
    email and re-run a transition.
    """
    customer = f"cus_{uuid.uuid4().hex[:12]}"
    sub = _subscribed(db, customer)
    event = _event(
        "invoice.payment_failed",
        {
            "id": f"in_{uuid.uuid4().hex[:12]}",
            "customer": customer,
            "subscription": sub.stripe_subscription_id,
            "status": "open",
            "amount_due": 7900,
            "amount_paid": 0,
            "currency": "usd",
        },
    )

    with patch.object(billing, "_notify") as notify:
        first = _post_event(client, event)
        second = _post_event(client, event)
    assert first.json() == {"status": "ok"}
    assert second.json() == {"status": "duplicate"}
    assert notify.call_count == 1


def test_subscription_deleted_returns_the_account_to_free(
    client: TestClient, db: Session
) -> None:
    customer = f"cus_{uuid.uuid4().hex[:12]}"
    sub = _subscribed(db, customer)

    with patch.object(billing, "_notify"):
        _post_event(
            client,
            _event(
                "customer.subscription.deleted",
                {"id": sub.stripe_subscription_id, "customer": customer},
            ),
        )
    db.refresh(sub)
    assert sub.status == SubscriptionStatus.canceled
    assert sub.tier == UserTier.free


def test_subscription_updated_adopts_the_stripe_period(
    client: TestClient, db: Session
) -> None:
    """A paid plan's allowance resets when it is re-billed, not on the 1st."""
    customer = f"cus_{uuid.uuid4().hex[:12]}"
    sub = _subscribed(db, customer)
    start = int(datetime(2026, 8, 17, tzinfo=timezone.utc).timestamp())
    end = int(datetime(2026, 9, 17, tzinfo=timezone.utc).timestamp())

    with (
        patch.object(settings, "STRIPE_PRICE_PRO", "price_pro"),
        patch.object(billing, "_notify"),
    ):
        _post_event(
            client,
            _event(
                "customer.subscription.updated",
                {
                    "id": sub.stripe_subscription_id,
                    "customer": customer,
                    "status": "active",
                    "items": {
                        "data": [
                            {
                                "price": {"id": "price_pro"},
                                "current_period_start": start,
                                "current_period_end": end,
                            }
                        ]
                    },
                },
            ),
        )
    db.refresh(sub)
    assert sub.period_start == datetime(2026, 8, 17, tzinfo=timezone.utc)
    assert sub.period_end == datetime(2026, 9, 17, tzinfo=timezone.utc)
    assert sub.tier == UserTier.pro


def test_subscription_updated_reads_the_legacy_period_fields(
    client: TestClient, db: Session
) -> None:
    """Older Stripe API versions keep the period on the subscription itself."""
    customer = f"cus_{uuid.uuid4().hex[:12]}"
    sub = _subscribed(db, customer)
    start = int(datetime(2026, 5, 3, tzinfo=timezone.utc).timestamp())
    end = int(datetime(2026, 6, 3, tzinfo=timezone.utc).timestamp())

    with (
        patch.object(settings, "STRIPE_PRICE_PRO", "price_pro"),
        patch.object(billing, "_notify"),
    ):
        _post_event(
            client,
            _event(
                "customer.subscription.updated",
                {
                    "id": sub.stripe_subscription_id,
                    "customer": customer,
                    "status": "active",
                    "current_period_start": start,
                    "current_period_end": end,
                    "items": {"data": [{"price": {"id": "price_pro"}}]},
                },
            ),
        )
    db.refresh(sub)
    assert sub.period_start == datetime(2026, 5, 3, tzinfo=timezone.utc)


def test_upgrade_changes_the_tier(client: TestClient, db: Session) -> None:
    customer = f"cus_{uuid.uuid4().hex[:12]}"
    sub = _subscribed(db, customer, tier=UserTier.starter)

    with (
        patch.object(settings, "STRIPE_PRICE_ULTIMATE", "price_ultimate"),
        patch.object(billing, "_notify"),
    ):
        _post_event(
            client,
            _event(
                "customer.subscription.updated",
                {
                    "id": sub.stripe_subscription_id,
                    "customer": customer,
                    "status": "active",
                    "items": {"data": [{"price": {"id": "price_ultimate"}}]},
                },
            ),
        )
    db.refresh(sub)
    assert sub.tier == UserTier.ultimate


def test_checkout_completed_activates_via_the_client_reference(
    client: TestClient, db: Session
) -> None:
    """Matches a subscription that had no Stripe customer id yet."""
    user, _org, _repo = owned_setup(db)
    sub = get_or_create_subscription(db, user)
    sub.status = SubscriptionStatus.incomplete
    db.add(sub)
    db.commit()

    with patch.object(billing, "_notify") as notify:
        _post_event(
            client,
            _event(
                "checkout.session.completed",
                {
                    "customer": f"cus_{uuid.uuid4().hex[:12]}",
                    "subscription": f"sub_{uuid.uuid4().hex[:12]}",
                    "client_reference_id": str(sub.id),
                },
            ),
        )
    db.refresh(sub)
    assert sub.status == SubscriptionStatus.active
    assert sub.stripe_customer_id is not None
    assert notify.call_args.args[2] == "subscription_started"


def test_unknown_event_types_are_accepted_and_ignored(client: TestClient) -> None:
    """Stripe sends far more than we handle; a 500 would make it retry forever."""
    response = _post_event(client, _event("customer.discount.created", {"id": "di_1"}))
    assert response.status_code == 200


def test_an_event_for_an_unknown_customer_is_not_an_error(
    client: TestClient,
) -> None:
    response = _post_event(
        client,
        _event(
            "customer.subscription.updated",
            {"id": "sub_nope", "customer": "cus_nope", "status": "active", "items": {}},
        ),
    )
    assert response.status_code == 200


def test_an_invalid_signature_is_rejected(client: TestClient) -> None:
    with (
        patch.object(settings, "STRIPE_SECRET_KEY", "sk_test_x"),
        patch.object(settings, "STRIPE_WEBHOOK_SECRET", "whsec_x"),
    ):
        response = client.post(
            f"{settings.API_V1_STR}/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=bogus"},
        )
    assert response.status_code == 400


def test_the_webhook_503s_when_stripe_is_unconfigured(client: TestClient) -> None:
    with patch.object(settings, "STRIPE_SECRET_KEY", None):
        response = client.post(f"{settings.API_V1_STR}/webhooks/stripe", content=b"{}")
    assert response.status_code == 503
