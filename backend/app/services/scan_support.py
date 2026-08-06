"""Pieces every scan worker needs, written once.

The four scan workers (CI workflow, Terraform, Docker, cloud posture) each open
with the same three chores before any engine-specific work happens: take a
per-target lock so two concurrent runs don't race on the same upserts, load the
enabled rules for their domain, and — at the end — resolve the findings the
latest scan no longer reports.

All three were copy-pasted per engine. The lock in particular is the kind of
duplication worth removing on correctness grounds rather than line count: it
nests two ``try``/``finally`` blocks to release the key *and* close the client,
and it was written out four times.

These take plain models and columns rather than an
:class:`~app.services.engines.EngineSpec`, so the cloud worker — which has no
spec, having no files or fixes — can use them too.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import redis as redis_sync
from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import FindingResolutionReason, Rule, RuleDomain
from app.services import state_machines as sm

logger = logging.getLogger(__name__)

# How long a single scan may hold its lock before the key expires on its own.
# A worker that dies mid-scan would otherwise block its target forever.
SCAN_LOCK_TTL_SECONDS = 600
# Longer for cloud posture, because that scan is bounded by the AWS API rather
# than by parsing: fourteen resource types across every configured region. It
# has to outlast the worst realistic scan, or the lock expires mid-run and a
# second scan races the first on CloudFinding upserts.
CLOUD_SCAN_LOCK_TTL_SECONDS = 3600


@contextmanager
def scan_lock(key: str, ttl_seconds: int = SCAN_LOCK_TTL_SECONDS) -> Iterator[bool]:
    """Hold ``greensecops:lock:<key>`` for the duration of a scan.

    Yields whether the lock was acquired; the caller decides what to do when it
    was not (every current caller re-queues itself). The key is always released
    and the client always closed, including on the failure paths.
    """
    lock_key = f"greensecops:lock:{key}"
    client = redis_sync.Redis.from_url(settings.REDIS_URL)
    try:
        acquired = bool(client.set(lock_key, "1", nx=True, ex=ttl_seconds))
        try:
            yield acquired
        finally:
            if acquired:
                client.delete(lock_key)
    finally:
        client.close()


def load_enabled_rules(session: Session, domain: RuleDomain) -> dict[str, Rule]:
    """The enabled rules of one engine, keyed by slug.

    A violation whose slug is missing from this map has no catalog row and is
    dropped by the caller with a warning — rules are seeded from the shipped
    ``.rego`` files (``core/rule_registry``), so that means a packaging bug,
    not a condition to work around.
    """
    return {
        rule.slug: rule
        for rule in session.exec(
            select(Rule).where(Rule.enabled == True).where(Rule.domain == domain)  # noqa: E712
        ).all()
    }


def resolve_stale_findings(
    session: Session,
    finding_model: type[Any],
    scope_field: str,
    scope_id: uuid.UUID,
    seen_fingerprints: set[str],
    label: str,
) -> int:
    """Resolve a target's open findings that the latest scan didn't report.

    Covers both the violation the user actually fixed and the one whose rule
    was removed or disabled since the previous scan — the two are
    indistinguishable from here, and both mean "no longer detected".

    Returns how many were resolved.
    """
    scope_col = getattr(finding_model, scope_field)
    open_findings = session.exec(
        select(finding_model)
        .where(scope_col == scope_id)
        .where(col(finding_model.resolved_at).is_(None))
    ).all()
    stale = [f for f in open_findings if f.fingerprint not in seen_fingerprints]
    if not stale:
        return 0

    now = datetime.now(timezone.utc)
    for finding in stale:
        sm.try_advance(finding, sm.FindingMachine, "resolve")
        finding.resolved_at = now
        finding.resolution_reason = FindingResolutionReason.no_longer_detected
        session.add(finding)
    session.commit()
    logger.info("Resolved %d stale %s finding(s) for %s", len(stale), label, scope_id)
    return len(stale)
