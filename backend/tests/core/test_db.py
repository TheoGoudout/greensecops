"""Tests for rule seeding and the release re-analysis trigger in initial_data."""

import uuid
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.core import db as db_module
from app.core.db import TERRAFORM_INITIAL_RULES, _seed_rules
from app.models import (
    IssueCategory,
    IssueSeverity,
    Organization,
    Repository,
    Rule,
    RuleDomain,
    UserTier,
)


def test_seed_rules_returns_empty_when_all_present(db: Session) -> None:
    # The session-scoped `db` fixture already ran init_db, so every rule exists.
    assert _seed_rules(db) == []


def test_terraform_rules_seeded_with_iac_terraform_domain(db: Session) -> None:
    for rule_data in TERRAFORM_INITIAL_RULES:
        rule = db.exec(select(Rule).where(Rule.slug == rule_data["slug"])).first()
        assert rule is not None
        assert rule.domain == RuleDomain.iac_terraform


def test_seed_rules_returns_newly_inserted_slug(db: Session) -> None:
    new_slug = f"throwaway-rule-{uuid.uuid4().hex[:8]}"
    extra = {
        "slug": new_slug,
        "category": IssueCategory.energy,
        "severity": IssueSeverity.low,
        "severity_weight": 0.5,
        "title": "Throwaway test rule",
        "description": "Temporary rule used only to exercise _seed_rules.",
    }
    with patch.object(db_module, "INITIAL_RULES", [*db_module.INITIAL_RULES, extra]):
        new_slugs = _seed_rules(db)

    try:
        assert new_slugs == [new_slug]
        # A second pass finds it already present and returns nothing for it.
        with patch.object(
            db_module, "INITIAL_RULES", [*db_module.INITIAL_RULES, extra]
        ):
            assert _seed_rules(db) == []
    finally:
        seeded = db.exec(select(Rule).where(Rule.slug == new_slug)).first()
        if seeded:
            db.delete(seeded)
            db.commit()


# ─── initial_data fan-out behaviour ──────────────────────────────────────────


@pytest.fixture()
def _org(db: Session) -> Organization:
    org = Organization(name=f"initdata-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def test_init_enqueues_reanalysis_when_new_rules_and_repos_exist(
    db: Session,
    _org: Organization,  # noqa: ARG001
) -> None:
    from app import initial_data

    # Ensure at least one repo exists so the guard passes.
    repo = Repository(
        org_id=_org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"initdata/repo-{uuid.uuid4().hex[:8]}",
        installation_id=40001,
    )
    db.add(repo)
    db.commit()

    with (
        patch.object(initial_data, "init_db", return_value=["some_new_rule"]),
        patch(
            "app.workers.tasks.static_analysis.reanalyze_all_repositories.delay"
        ) as mock_delay,
    ):
        initial_data.init()

    mock_delay.assert_called_once()


def test_init_does_not_enqueue_when_no_new_rules(db: Session) -> None:  # noqa: ARG001
    from app import initial_data

    with (
        patch.object(initial_data, "init_db", return_value=[]),
        patch(
            "app.workers.tasks.static_analysis.reanalyze_all_repositories.delay"
        ) as mock_delay,
    ):
        initial_data.init()

    mock_delay.assert_not_called()
