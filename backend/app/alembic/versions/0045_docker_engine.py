"""Add the Docker/Compose analysis engine tables

Companion to the ``container_docker`` Rego domain. Mirrors
``0042_iac_cloud_foundations`` in shape: enum columns are plain varchar
(``AutoString``) with raw-string server defaults rather than Postgres ENUM
types, so adding a status value later is a code change and not a migration.

No ``rule.domain`` change is needed — 0042 added that column and
``container_docker`` is simply another value in it.

Revision ID: 0045
Revises: 0044
"""

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "docker_target",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repo_id", sa.Uuid(), nullable=False),
        sa.Column(
            "root_path", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "last_scanned_head_sha",
            sqlmodel.sql.sqltypes.AutoString(length=40),
            nullable=True,
        ),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["repo_id"], ["repository.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repo_id", "root_path", name="uq_docker_target_repo_path"),
    )

    op.create_table(
        "docker_scan",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("docker_target_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("triggered_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "branch", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True
        ),
        sa.Column(
            "commit_sha", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True
        ),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("grade", sqlmodel.sql.sqltypes.AutoString(length=8), nullable=True),
        sa.Column("file_count", sa.Integer(), nullable=True),
        sa.Column(
            "error_message",
            sqlmodel.sql.sqltypes.AutoString(length=2048),
            nullable=True,
        ),
        sa.Column("failure_kind", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["docker_target_id"], ["docker_target.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "docker_finding",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("docker_target_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column(
            "file_path", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False
        ),
        sa.Column(
            "service_name", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True
        ),
        sa.Column(
            "stage_name", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True
        ),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column(
            "fingerprint", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False
        ),
        sa.Column("severity", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="open",
        ),
        sa.Column(
            "message", sqlmodel.sql.sqltypes.AutoString(length=2048), nullable=False
        ),
        sa.Column(
            "context", sqlmodel.sql.sqltypes.AutoString(length=4096), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolution_reason", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
        sa.Column("ignored_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["scan_id"], ["docker_scan.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["docker_target_id"], ["docker_target.id"], ondelete="CASCADE"
        ),
        # RESTRICT, not CASCADE: deleting a Rule must not silently take its
        # findings' history with it.
        sa.ForeignKeyConstraint(["rule_id"], ["rule.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "docker_target_id",
            "fingerprint",
            name="uq_docker_finding_target_fingerprint",
        ),
    )
    op.create_index("ix_docker_finding_fingerprint", "docker_finding", ["fingerprint"])
    op.create_index("ix_docker_finding_status", "docker_finding", ["status"])


def downgrade() -> None:
    op.drop_index("ix_docker_finding_status", table_name="docker_finding")
    op.drop_index("ix_docker_finding_fingerprint", table_name="docker_finding")
    op.drop_table("docker_finding")
    op.drop_table("docker_scan")
    op.drop_table("docker_target")
