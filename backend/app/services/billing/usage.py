"""The usage ledger — what got charged, when, and by which engine.

## What counts

GreenSecOps runs five analysis engines (CI workflow, Terraform, Docker, AWS
cloud posture, CI telemetry) and they all draw from one shared ``analyses``
allowance, because to a user they are one product. Before this module only the
workflow engine was metered at all; a Terraform root scanned on every push, a
Docker target, a cloud account and every LLM-backed Terraform/Docker fix were
free forever.

## When a unit is charged

The rule is: **a record is written when the work is created, not when it
finishes.**

That ordering is not incidental. Charging on completion leaves in-flight work
invisible, so two triggers arriving together both read the old total, both pass
the check, and both run. Charging at creation makes the ledger monotonic within
a period, which is the property enforcement actually needs.

Three things deliberately cost nothing:

* **Duplicate content.** A workflow file whose content hash matches its last
  analysis is answered from the previous result without inserting a row, so no
  record is written. This is the behaviour the pricing FAQ promises.
* **Nothing to analyse.** ``no_workflows`` / ``no_targets`` outcomes evaluated
  no rules. Fetching an empty directory is not a billable analysis.
* **Our own retries.** The maintenance sweeper re-dispatching an analysis that
  failed transiently (a worker crash, an OPA hiccup) passes ``billable=False``.
  The user did not ask for that run and should not pay for our flakiness.

A genuine ``failed`` analysis *does* count. The compute was spent, and not
charging for it turns failure into an unlimited free retry loop.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlmodel import Session, col, func, select

from app.models import (
    BillingUsageRecord,
    Repository,
    UsageEngine,
    UsageMeter,
)

from .owner import billing_owner_org_ids, org_billing_owner

logger = logging.getLogger(__name__)


def record_usage(
    session: Session,
    *,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    meter: UsageMeter,
    engine: UsageEngine,
    source_type: str,
    source_id: uuid.UUID | None = None,
    repo_id: uuid.UUID | None = None,
    quantity: int = 1,
    occurred_at: datetime | None = None,
    commit: bool = True,
) -> BillingUsageRecord:
    """Append one ledger entry.

    ``commit=False`` lets a caller fold the charge into a surrounding
    transaction — the workers write the record in the same unit of work that
    creates the analysis row, so a rolled-back analysis cannot leave a phantom
    charge behind.
    """
    record = BillingUsageRecord(
        user_id=user_id,
        org_id=org_id,
        repo_id=repo_id,
        meter=meter,
        engine=engine,
        quantity=quantity,
        source_type=source_type,
        source_id=source_id,
        **({"occurred_at": occurred_at} if occurred_at is not None else {}),
    )
    session.add(record)
    if commit:
        session.commit()
    else:
        session.flush()
    return record


def record_for_org(
    session: Session,
    *,
    org_id: uuid.UUID,
    meter: UsageMeter,
    engine: UsageEngine,
    source_type: str,
    source_id: uuid.UUID | None = None,
    repo_id: uuid.UUID | None = None,
    quantity: int = 1,
    commit: bool = True,
) -> BillingUsageRecord | None:
    """Charge ``org_id``'s billing owner, resolving them first.

    Returns ``None`` when the org has no resolvable owner — an org linked in a
    way that left no owner member has nobody to bill, and refusing to analyse
    it would punish the user for our bookkeeping. This mirrors how
    ``quota.enforce`` no-ops in the same situation, so an unattributable org is
    consistently neither charged nor blocked.
    """
    owner = org_billing_owner(session, org_id)
    if owner is None:
        logger.debug("No billing owner for org %s — usage not recorded", org_id)
        return None
    return record_usage(
        session,
        user_id=owner.id,
        org_id=org_id,
        meter=meter,
        engine=engine,
        source_type=source_type,
        source_id=source_id,
        repo_id=repo_id,
        quantity=quantity,
        commit=commit,
    )


def record_for_repo(
    session: Session,
    *,
    repo: Repository,
    meter: UsageMeter,
    engine: UsageEngine,
    source_type: str,
    source_id: uuid.UUID | None = None,
    quantity: int = 1,
    commit: bool = True,
) -> BillingUsageRecord | None:
    """``record_for_org`` for the common case where a repository is in hand."""
    return record_for_org(
        session,
        org_id=repo.org_id,
        meter=meter,
        engine=engine,
        source_type=source_type,
        source_id=source_id,
        repo_id=repo.id,
        quantity=quantity,
        commit=commit,
    )


def period_usage(
    session: Session,
    user_id: uuid.UUID,
    meter: UsageMeter,
    period_start: datetime | None,
    period_end: datetime | None,
) -> int:
    """``SUM(quantity)`` for one meter over ``[period_start, period_end)``.

    An open-ended bound is simply not applied, so a subscription with no period
    yet reports its whole ledger rather than zero — safer to over-report than
    to hand out a free month to a row the rollover has not touched.
    """
    query = select(func.coalesce(func.sum(BillingUsageRecord.quantity), 0)).where(
        BillingUsageRecord.user_id == user_id,
        BillingUsageRecord.meter == meter,
    )
    if period_start is not None:
        query = query.where(col(BillingUsageRecord.occurred_at) >= period_start)
    if period_end is not None:
        query = query.where(col(BillingUsageRecord.occurred_at) < period_end)
    return int(session.exec(query).one() or 0)


def period_breakdown(
    session: Session,
    user_id: uuid.UUID,
    period_start: datetime | None,
    period_end: datetime | None,
) -> list[tuple[UsageMeter, UsageEngine, int]]:
    """Per-(meter, engine) totals for the period, biggest spender first.

    This is what answers "why am I at 90%" — with counters there was no way to
    tell a user it was their Terraform roots rather than their workflows.
    """
    total = func.coalesce(func.sum(BillingUsageRecord.quantity), 0).label("total")
    query = select(BillingUsageRecord.meter, BillingUsageRecord.engine, total).where(
        BillingUsageRecord.user_id == user_id
    )
    if period_start is not None:
        query = query.where(col(BillingUsageRecord.occurred_at) >= period_start)
    if period_end is not None:
        query = query.where(col(BillingUsageRecord.occurred_at) < period_end)
    query = query.group_by(
        col(BillingUsageRecord.meter), col(BillingUsageRecord.engine)
    ).order_by(total.desc())
    # The columns are VARCHAR (every status enum in this schema is), so the
    # driver hands back plain strings. Coerce them so callers get the enums the
    # signature promises rather than values that only happen to compare equal.
    return [
        (UsageMeter(meter), UsageEngine(engine), int(quantity))
        for meter, engine, quantity in session.exec(query)
    ]


def enabled_repo_ids(session: Session, user_id: uuid.UUID) -> list[uuid.UUID]:
    """Repositories currently enabled across the orgs ``user_id`` pays for.

    The ``repos`` meter is capacity, not consumption: it is measured live
    rather than from the ledger, because disabling a repository frees the slot
    immediately instead of at the next period boundary.
    """
    org_ids = billing_owner_org_ids(session, user_id)
    if not org_ids:
        return []
    return list(
        session.exec(
            select(Repository.id).where(
                col(Repository.org_id).in_(org_ids),
                Repository.enabled == True,  # noqa: E712
            )
        ).all()
    )
