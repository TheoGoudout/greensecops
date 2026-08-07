"""The worker-side quota gate — the one that actually holds.

The API pre-check cannot enforce anything on its own, for two reasons these
tests pin down:

1. A single trigger fans out to one analysis *per workflow file*, so a check
   for "1" let a user one below their cap create twenty.
2. Most analyses never touch an API route at all. Push webhooks, the polling
   sweep and installation sync all dispatch straight into these workers, and
   none of them called ``enforce_quota``.

Putting the real gate in the worker covers every one of those paths at once.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.core import plans
from app.core.plans import Plan, PlanLimits
from app.models import BillingUsageRecord, UsageEngine, UsageMeter, UserTier
from app.services.billing import quota
from app.workers.tasks import terraform_analysis
from tests.utils.billing import make_terraform_root, owned_setup, record_usage


@pytest.fixture
def free_allows_two(monkeypatch: pytest.MonkeyPatch) -> None:
    """Free tier capped at two analyses, so the wall is cheap to reach."""
    base = plans.PLANS[UserTier.free]
    patched = dict(plans.PLANS)
    patched[UserTier.free] = Plan(
        tier=base.tier,
        name=base.name,
        price_cents=base.price_cents,
        tagline=base.tagline,
        limits=PlanLimits(analyses=2, fixes=1, repos=5),
        auto_fix=base.auto_fix,
        public_repos_only=base.public_repos_only,
        stripe_price_setting=base.stripe_price_setting,
        features=base.features,
    )
    monkeypatch.setattr(plans, "PLANS", patched)


def _ledger(db: Session, user_id, meter: UsageMeter = UsageMeter.analyses) -> int:  # type: ignore[no-untyped-def]
    rows = db.exec(
        select(BillingUsageRecord)
        .where(BillingUsageRecord.user_id == user_id)
        .where(BillingUsageRecord.meter == meter)
    ).all()
    return sum(r.quantity for r in rows)


# ─── The gate stops work before it starts ────────────────────────────────────


def test_terraform_scan_is_refused_when_the_allowance_is_spent(
    db: Session, free_allows_two: None
) -> None:
    """And refused *before* the GitHub fetch, which is the expensive part."""
    user, org, repo = owned_setup(db)
    root = make_terraform_root(db, repo)
    for _ in range(2):
        record_usage(db, user, org, meter=UsageMeter.analyses)

    with patch.object(terraform_analysis, "_fetch_terraform_files") as fetch:
        result = terraform_analysis._run_terraform_scan_impl(str(root.id))

    assert result["status"] == "quota_exceeded"
    # The gate ran first: no network call, no scan row, no charge.
    assert fetch.call_count == 0
    assert "Free plan" in str(result["detail"])
    assert _ledger(db, user.id) == 2


def test_terraform_scan_runs_while_allowance_remains(
    db: Session, free_allows_two: None
) -> None:
    user, org, repo = owned_setup(db)
    root = make_terraform_root(db, repo)
    record_usage(db, user, org, meter=UsageMeter.analyses)  # 1 of 2

    with patch.object(terraform_analysis, "_fetch_terraform_files", return_value=[]):
        result = terraform_analysis._run_terraform_scan_impl(str(root.id))

    # An empty root is deliberately uncharged — nothing was evaluated.
    assert result["status"] == "no_targets"
    assert _ledger(db, user.id) == 1


def test_an_unbillable_run_skips_the_gate_entirely(
    db: Session, free_allows_two: None
) -> None:
    """Our own retry of our own transient failure: not blocked, not billed."""
    user, org, repo = owned_setup(db)
    root = make_terraform_root(db, repo)
    for _ in range(5):  # well past the cap
        record_usage(db, user, org, meter=UsageMeter.analyses)

    with patch.object(terraform_analysis, "_fetch_terraform_files", return_value=[]):
        result = terraform_analysis._run_terraform_scan_impl(
            str(root.id), billable=False
        )

    assert result["status"] != "quota_exceeded"
    assert _ledger(db, user.id) == 5  # unchanged


# ─── The batch bug ───────────────────────────────────────────────────────────


def test_remaining_is_what_bounds_a_batch(db: Session, free_allows_two: None) -> None:
    """The countdown the static-analysis loop uses per workflow file.

    ``static_analysis`` reads this once and decrements it as it creates rows,
    stopping the loop at zero. That is what turns "one analysis per workflow
    file" from an unbounded fan-out into a bounded one.
    """
    user, org, _repo = owned_setup(db)
    assert quota.remaining(db, None, org.id, "analyses") == 2
    record_usage(db, user, org, meter=UsageMeter.analyses)
    assert quota.remaining(db, None, org.id, "analyses") == 1
    record_usage(db, user, org, meter=UsageMeter.analyses)
    assert quota.remaining(db, None, org.id, "analyses") == 0


def test_a_webhook_triggered_scan_is_gated_like_any_other(
    db: Session, free_allows_two: None
) -> None:
    """Regression: webhook and polling paths bypassed quota completely.

    They dispatch straight into the worker with no route in between, so this is
    the only place a check could ever have caught them.
    """
    user, org, repo = owned_setup(db)
    root = make_terraform_root(db, repo)
    for _ in range(2):
        record_usage(db, user, org, meter=UsageMeter.analyses)

    with patch.object(terraform_analysis, "_fetch_terraform_files") as fetch:
        result = terraform_analysis._run_terraform_scan_impl(
            str(root.id), trigger="webhook_push"
        )
    assert result["status"] == "quota_exceeded"
    assert fetch.call_count == 0


# ─── Charging is per engine ──────────────────────────────────────────────────


def test_a_terraform_scan_is_charged_to_the_owner(db: Session) -> None:
    """Terraform scans were previously never metered at all."""
    user, _org, repo = owned_setup(db)
    root = make_terraform_root(db, repo)

    class _File:
        path = "main.tf"
        content = 'resource "aws_s3_bucket" "b" {}\n'

    with (
        patch.object(
            terraform_analysis, "_fetch_terraform_files", return_value=[_File()]
        ),
        patch.object(
            terraform_analysis, "_evaluate", side_effect=RuntimeError("no opa")
        ),
    ):
        result = terraform_analysis._run_terraform_scan_impl(str(root.id))

    # Even a failed evaluation counts: the work was dispatched and the compute
    # spent. Not charging would make failure an unlimited free retry loop.
    assert result["status"] == "failed"
    records = db.exec(
        select(BillingUsageRecord).where(BillingUsageRecord.user_id == user.id)
    ).all()
    assert len(records) == 1
    assert records[0].engine == UsageEngine.terraform
    assert records[0].meter == UsageMeter.analyses
    assert records[0].repo_id == repo.id
    assert records[0].source_type == "terraform_scan"
