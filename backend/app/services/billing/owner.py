"""Resolving *who pays* for an organisation's usage.

Usage is always measured against an org's **billing owner**, never against
whoever happened to trigger the work. Without that, a teammate on a shared org
would draw from their own untouched personal quota and sail past the owner's
exhausted one.

Moved here from ``api/routes/billing.py`` unchanged in behaviour: the workers
need the same resolution as the routes, and a worker importing an API route
module to get at it would be backwards.
"""

from __future__ import annotations

import uuid

from sqlmodel import Session, col, select

from app.models import OrgMember, OrgRole, User


def org_billing_owner(session: Session, org_id: uuid.UUID) -> User | None:
    """Return the user whose tier/subscription an org's usage counts against.

    The billing owner is the earliest-joined ``owner`` member of the org.
    Every org gets an owner member the moment it's linked (``add_org_owner``),
    but a shared GitHub org can end up with several owner members if more than
    one person links it — ordering by ``joined_at`` keeps that resolution
    stable instead of arbitrary, so later members don't pool usage into (or
    borrow quota from) their own separate personal tier.
    """
    member = session.exec(
        select(OrgMember)
        .where(OrgMember.org_id == org_id, OrgMember.role == OrgRole.owner)
        .order_by(col(OrgMember.joined_at), col(OrgMember.user_id))
    ).first()
    if member is None:
        return None
    return session.get(User, member.user_id)


def billing_owner_org_ids(session: Session, user_id: uuid.UUID) -> list[uuid.UUID]:
    """Return org ids whose usage counts against ``user_id``'s tier.

    Restricted to orgs where this user is the resolved billing owner, so a
    user merely riding along as a later owner/member of someone else's org
    doesn't inherit that org's usage.
    """
    owned_org_ids = session.exec(
        select(OrgMember.org_id).where(
            OrgMember.user_id == user_id, OrgMember.role == OrgRole.owner
        )
    ).all()
    return [
        org_id
        for org_id in owned_org_ids
        if (owner := org_billing_owner(session, org_id)) is not None
        and owner.id == user_id
    ]
