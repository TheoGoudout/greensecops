"""Add TelemetryMetricSample table and phase column to TelemetryRun

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-11

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "telemetry_run",
        sa.Column("phase", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
    )

    op.create_table(
        "telemetry_metric_sample",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repo_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Integer(), nullable=False),
        sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cpu_percent", sa.Float(), nullable=True),
        sa.Column("ram_used_mb", sa.Float(), nullable=True),
        sa.Column("disk_used_gb", sa.Float(), nullable=True),
        sa.Column("net_bytes_sent", sa.BigInteger(), nullable=True),
        sa.Column("net_bytes_recv", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["repo_id"], ["repository.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_telemetry_metric_sample_workflow_run_id"),
        "telemetry_metric_sample",
        ["workflow_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_telemetry_metric_sample_workflow_run_id"),
        table_name="telemetry_metric_sample",
    )
    op.drop_table("telemetry_metric_sample")
    op.drop_column("telemetry_run", "phase")
