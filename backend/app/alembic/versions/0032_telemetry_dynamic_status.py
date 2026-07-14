"""Add telemetry_run.dynamic_status

Revision ID: 0032
Revises: 0031
Create Date: 2026-07-14

Tracks the dynamic-analysis/enrichment lifecycle (queued/running/enriched/
failed) for a ``completed``-phase telemetry run, owned by the TelemetryMachine.
Nullable — ``started``-phase rows never enrich, so their dynamic_status stays
NULL. Plain string column (enum stored as text).
"""

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "telemetry_run",
        sa.Column("dynamic_status", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("telemetry_run", "dynamic_status")
