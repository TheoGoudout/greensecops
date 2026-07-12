"""Add dynamic_enrichment table

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-12

Persists the runtime findings produced by dynamic analysis (previously only
logged), linked to the telemetry run that produced them and, when available,
the latest completed analysis they enrich.
"""

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dynamic_enrichment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repo_id", sa.Uuid(), nullable=False),
        sa.Column("telemetry_run_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=True),
        sa.Column("rule_slug", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
        sa.Column("evidence", sqlmodel.sql.sqltypes.AutoString(length=2048), nullable=False),
        sa.Column(
            "recommendation",
            sqlmodel.sql.sqltypes.AutoString(length=2048),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["repo_id"], ["repository.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["telemetry_run_id"], ["telemetry_run.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["analysis.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dynamic_enrichment_rule_slug", "dynamic_enrichment", ["rule_slug"]
    )


def downgrade() -> None:
    op.drop_index("ix_dynamic_enrichment_rule_slug", table_name="dynamic_enrichment")
    op.drop_table("dynamic_enrichment")
