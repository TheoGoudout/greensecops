import logging

from sqlmodel import Session, select

from app.core.db import engine, init_db
from app.models import Repository

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init() -> list[str]:
    with Session(engine) as session:
        new_rule_slugs = init_db(session)
        # When a release ships new rules, fan out a fresh analysis across all
        # known repositories so the new rules are applied and grades recomputed
        # — much like an inbound webhook triggers analysis for a single repo.
        # Skip the very first bootstrap (no repos exist yet) to avoid a needless
        # mass run when every rule is "new".
        if new_rule_slugs:
            has_repos = session.exec(select(Repository)).first() is not None
            if has_repos:
                from app.workers.tasks.static_analysis import (
                    reanalyze_all_repositories,
                )

                reanalyze_all_repositories.delay()
                logger.info(
                    "Seeded %d new rule(s) %s; enqueued re-analysis of all repos",
                    len(new_rule_slugs),
                    new_rule_slugs,
                )
        return new_rule_slugs


def main() -> None:
    logger.info("Creating initial data")
    init()
    logger.info("Initial data created")


if __name__ == "__main__":
    main()
