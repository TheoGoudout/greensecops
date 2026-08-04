"""Tests for rule seeding and the release re-analysis trigger in initial_data."""

import uuid
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.core import db as db_module
from app.core.db import _seed_rules
from app.core.rule_registry import discover_rules
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


def test_every_shipped_rego_rule_has_a_row(db: Session) -> None:
    """The seed covers the whole catalog, whatever engine a rule belongs to.

    Replaces the per-list assertions that existed while the catalog was six
    hand-written lists: the registry *is* the list now, so the useful check is
    that seeding it leaves nothing behind.
    """
    rows = {(r.domain, r.slug) for r in db.exec(select(Rule)).all()}
    for rule_data in discover_rules():
        assert (rule_data["domain"], rule_data["slug"]) in rows


def test_terraform_rules_seeded_with_iac_terraform_domain(db: Session) -> None:
    terraform = [r for r in discover_rules() if r["domain"] == RuleDomain.iac_terraform]
    assert terraform, "expected at least one iac_terraform rule"
    for rule_data in terraform:
        rule = db.exec(
            select(Rule)
            .where(Rule.slug == rule_data["slug"])
            .where(Rule.domain == RuleDomain.iac_terraform)
        ).first()
        assert rule is not None
        assert rule.domain == RuleDomain.iac_terraform


def test_slug_shared_across_engines_gets_a_row_per_engine(db: Session) -> None:
    """Regression for the three cloud rules that used to be dropped silently.

    ``slug`` was globally unique, so seeding inserted the Terraform copy of
    ``rds_not_encrypted`` and skipped the cloud one — and ``cloud_scan``'s
    ``Rule.domain == cloud_aws`` lookup then found nothing and discarded every
    finding that rule produced. Migration 0048 keys rules on (domain, slug).
    """
    shared = {
        r["slug"] for r in discover_rules() if r["domain"] == RuleDomain.cloud_aws
    } & {r["slug"] for r in discover_rules() if r["domain"] == RuleDomain.iac_terraform}
    assert shared, "expected at least one slug shared between the cloud and IaC engines"

    for slug in shared:
        domains = {
            r.domain for r in db.exec(select(Rule).where(Rule.slug == slug)).all()
        }
        assert RuleDomain.cloud_aws in domains
        assert RuleDomain.iac_terraform in domains


def test_seed_rules_returns_newly_inserted_slug(db: Session) -> None:
    new_slug = f"throwaway-rule-{uuid.uuid4().hex[:8]}"
    extra = {
        "slug": new_slug,
        "domain": RuleDomain.workflow,
        "category": IssueCategory.energy,
        "severity": IssueSeverity.low,
        "severity_weight": 0.5,
        "title": "Throwaway test rule",
        "description": "Temporary rule used only to exercise _seed_rules.",
    }
    discovered = discover_rules()
    with patch.object(db_module, "discover_rules", return_value=[*discovered, extra]):
        new_slugs = _seed_rules(db)

        try:
            assert new_slugs == [new_slug]
            # A second pass finds it already present and returns nothing for it.
            assert _seed_rules(db) == []
        finally:
            seeded = db.exec(select(Rule).where(Rule.slug == new_slug)).first()
            if seeded:
                db.delete(seeded)
                db.commit()


def test_seed_rules_updates_a_row_whose_metadata_changed(db: Session) -> None:
    """Editing a METADATA block is enough — the seed no longer skips existing rows."""
    original = discover_rules()[0]
    edited = {**original, "title": "Retitled by the seeding test"}

    row = db.exec(
        select(Rule)
        .where(Rule.slug == original["slug"])
        .where(Rule.domain == original["domain"])
    ).one()
    previous_title = row.title

    try:
        with patch.object(
            db_module,
            "discover_rules",
            return_value=[edited, *discover_rules()[1:]],
        ):
            assert _seed_rules(db) == []
        db.refresh(row)
        assert row.title == "Retitled by the seeding test"
    finally:
        row.title = previous_title
        db.add(row)
        db.commit()


def test_seed_rules_leaves_enabled_alone(db: Session) -> None:
    """A rule an operator disabled in the admin UI stays disabled across a deploy."""
    row = db.exec(select(Rule)).first()
    assert row is not None
    row.enabled = False
    db.add(row)
    db.commit()

    try:
        _seed_rules(db)
        db.refresh(row)
        assert row.enabled is False
    finally:
        row.enabled = True
        db.add(row)
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
