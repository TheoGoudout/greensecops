"""Add telemetry_metric_sample.top_processes

Revision ID: 0039
Revises: 0038
Create Date: 2026-07-20

The telemetry action's proc-sampler binary reports the top 5-10%
resource-consuming processes per sample tick (Linux runners only). Stored
as JSON text alongside the existing flat metric columns, same convention
as telemetry_run.metrics/runner_specs.
"""

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "telemetry_metric_sample",
        sa.Column("top_processes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("telemetry_metric_sample", "top_processes")
