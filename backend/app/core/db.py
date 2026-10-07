import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import SessionTransaction
from sqlmodel import Session, create_engine, select

from app import crud
from app.core.config import settings
from app.core.rule_registry import discover_rules
from app.models import (
    Rule,
    User,
    UserCreate,
)

logger = logging.getLogger(__name__)

engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))


# ─── Side effects that must wait for the commit ──────────────────────────────
#
# An SSE event or an email announcing a change must not go out for a
# transaction that then rolls back, and code that changes state should not have
# to commit just to be allowed to announce it — committing in the middle of a
# caller's transaction is exactly what makes a multi-step write non-atomic.
# Code that changes state queues its announcement with ``after_commit``; whoever
# owns the transaction ends it with ``commit``.

_AFTER_COMMIT = "after_commit_effects"


def after_commit(session: Session, effect: Callable[[], Any]) -> None:
    """Run ``effect`` once ``commit(session)`` has committed the transaction.

    Dropped if the transaction rolls back instead. Effects run in the order
    they were queued.
    """
    session.info.setdefault(_AFTER_COMMIT, []).append(effect)


def commit(session: Session) -> None:
    """Commit, then run the effects queued for this transaction."""
    effects: list[Callable[[], Any]] = session.info.pop(_AFTER_COMMIT, [])
    session.commit()
    for effect in effects:
        effect()


@event.listens_for(Session, "after_soft_rollback")
def _drop_effects_on_rollback(
    session: Session, previous_transaction: SessionTransaction
) -> None:
    # Only the outermost transaction: a savepoint rolling back leaves the
    # enclosing transaction, and what it queued, intact.
    if previous_transaction.parent is None:
        session.info.pop(_AFTER_COMMIT, None)


def _seed_rules(session: Session) -> list[str]:
    """Sync the ``rule`` table with the shipped Rego policies.

    The catalog is derived from the ``.rego`` files themselves
    (``app.core.rule_registry``), not from a list maintained beside them — see
    that module for why. Rules are matched on ``(domain, slug)``: the same slug
    is a distinct rule in a distinct engine.

    Existing rows are **updated** rather than left alone, so editing a METADATA
    block is enough to correct a rule's severity, weight or wording; previously
    the seed skipped anything already present and the two copies drifted.
    ``enabled`` is deliberately not touched — an operator who disabled a rule in
    the admin UI should not have it switched back on by a deploy.

    Returns the slugs of newly inserted rules, so callers can detect when a
    release has shipped new rules.
    """
    new_slugs: list[str] = []
    existing_rules = {
        (rule.domain, rule.slug): rule for rule in session.exec(select(Rule)).all()
    }

    for rule_data in discover_rules():
        key = (rule_data["domain"], rule_data["slug"])
        existing = existing_rules.get(key)
        if existing is None:
            session.add(Rule.model_validate(rule_data))
            new_slugs.append(str(rule_data["slug"]))
            continue
        for field, value in rule_data.items():
            if getattr(existing, field) != value:
                setattr(existing, field, value)
                session.add(existing)

    session.commit()
    if new_slugs:
        logger.info("Seeded %d new rule(s): %s", len(new_slugs), ", ".join(new_slugs))
    return new_slugs


def init_db(session: Session) -> list[str]:
    """Create initial data and return the slugs of any newly seeded rules."""
    user = session.exec(
        select(User).where(User.email == settings.FIRST_SUPERUSER)
    ).first()
    if not user:
        user_in = UserCreate(
            email=settings.FIRST_SUPERUSER,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            is_superuser=True,
        )
        user = crud.create_user(session=session, user_create=user_in)

    return _seed_rules(session)
