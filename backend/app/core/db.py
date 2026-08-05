import logging

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
