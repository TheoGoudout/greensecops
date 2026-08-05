"""Key rules by (domain, slug) instead of slug alone

``ix_rule_slug`` has been unique since 0001, from when there was one engine and
a slug was an unambiguous name. There are six engines now, and the same finding
is legitimately a rule in more than one of them: ``rds_not_encrypted`` is a
Terraform finding *and* a live-account finding, with its own severity and score
on each side.

A globally unique slug made those collisions unrepresentable. ``_seed_rules``
inserted whichever engine's list came first (Terraform) and skipped the rest, so
``open_ingress_security_group``, ``rds_not_encrypted`` and
``s3_bucket_missing_versioning`` had no ``cloud_aws`` row — and
``cloud_scan``'s ``Rule.domain == cloud_aws`` lookup therefore found nothing and
dropped every finding those three rules produced, with only a log line to say
so.

This swaps the unique index on ``slug`` for a non-unique one plus a
``(domain, slug)`` unique constraint. Existing rows already satisfy it; the
three missing cloud rows are created by the next seed.

Revision ID: 0048
Revises: 0047
"""

from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Slug lookups are still per-slug (scoped by domain in the query), so the
    # index stays — it just stops carrying the uniqueness guarantee.
    op.drop_index(op.f("ix_rule_slug"), table_name="rule")
    op.create_index(op.f("ix_rule_slug"), "rule", ["slug"], unique=False)
    op.create_unique_constraint("uq_rule_domain_slug", "rule", ["domain", "slug"])


def downgrade() -> None:
    # Only reversible while no two engines share a slug. Once the cloud rows
    # exist, the unique index below cannot be built and the downgrade fails
    # loudly — which is correct: reinstating it would mean deciding which
    # engine's copy of a rule to delete, along with its findings.
    op.drop_constraint("uq_rule_domain_slug", "rule", type_="unique")
    op.drop_index(op.f("ix_rule_slug"), table_name="rule")
    op.create_index(op.f("ix_rule_slug"), "rule", ["slug"], unique=True)
