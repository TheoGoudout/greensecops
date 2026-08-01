"""Add Docker build/runtime telemetry

The dynamic counterpart of the container_docker engine. Two tables rather
than an extension of ``telemetry_run``: that row is keyed on
``workflow_run_id`` and models one runner per run, while a workflow builds
several images — the cardinality is wrong and it would mix two rule domains
into one payload.

``docker_build_enrichment`` is a sibling of ``dynamic_enrichment``, not a
generalisation of it, matching the call made when terraform_finding was added
beside issue.

Revision ID: 0047
Revises: 0046
"""

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "docker_build_telemetry",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repo_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "image_ref", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True
        ),
        sa.Column(
            "dockerfile_path",
            sqlmodel.sql.sqltypes.AutoString(length=512),
            nullable=True,
        ),
        sa.Column("image_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("context_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("build_duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("cache_hit_ratio", sa.Float(), nullable=True),
        sa.Column("layers", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("containers", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["repo_id"], ["repository.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_docker_build_telemetry_workflow_run_id",
        "docker_build_telemetry",
        ["workflow_run_id"],
    )

    op.create_table(
        "docker_build_enrichment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repo_id", sa.Uuid(), nullable=False),
        sa.Column("telemetry_id", sa.Uuid(), nullable=False),
        sa.Column(
            "rule_slug", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False
        ),
        sa.Column(
            "evidence", sqlmodel.sql.sqltypes.AutoString(length=2048), nullable=False
        ),
        sa.Column(
            "recommendation",
            sqlmodel.sql.sqltypes.AutoString(length=2048),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["repo_id"], ["repository.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["telemetry_id"], ["docker_build_telemetry.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_docker_build_enrichment_rule_slug",
        "docker_build_enrichment",
        ["rule_slug"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_docker_build_enrichment_rule_slug", table_name="docker_build_enrichment"
    )
    op.drop_table("docker_build_enrichment")
    op.drop_index(
        "ix_docker_build_telemetry_workflow_run_id",
        table_name="docker_build_telemetry",
    )
    op.drop_table("docker_build_telemetry")
