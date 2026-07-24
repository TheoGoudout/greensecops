"""Add IaC (Terraform) and cloud posture analysis foundations

Revision ID: 0042
Revises: 0041
Create Date: 2026-07-23

Schema foundation for the new Terraform static analysis and AWS cloud
posture analysis engines, run alongside the existing CI-workflow engine:

- ``rule.domain`` discriminates which engine a Rule belongs to (existing
  rows backfilled to ``workflow``), so one Rule table/admin UI serves all
  three engines instead of three parallel tables.
- ``terraform_root`` / ``terraform_scan`` / ``terraform_finding`` mirror
  ``workflow_file`` / ``analysis`` / ``issue`` for Terraform roots configured
  on a repo.
- ``cloud_account`` / ``cloud_scan`` / ``cloud_finding`` are the org-level
  (not repo-level) equivalent for a connected AWS account.
"""

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rule",
        sa.Column(
            "domain",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="workflow",
        ),
    )

    op.create_table(
        "terraform_root",
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
        sa.UniqueConstraint(
            "repo_id", "root_path", name="uq_terraform_root_repo_path"
        ),
    )

    op.create_table(
        "terraform_scan",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("terraform_root_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column(
            "triggered_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column(
            "branch", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True
        ),
        sa.Column(
            "commit_sha", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True
        ),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column(
            "grade", sqlmodel.sql.sqltypes.AutoString(length=8), nullable=True
        ),
        sa.Column(
            "artifact_object_key",
            sqlmodel.sql.sqltypes.AutoString(length=512),
            nullable=True,
        ),
        sa.Column(
            "error_message",
            sqlmodel.sql.sqltypes.AutoString(length=2048),
            nullable=True,
        ),
        sa.Column(
            "failure_kind", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["terraform_root_id"], ["terraform_root.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "terraform_finding",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("terraform_root_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column(
            "resource_address",
            sqlmodel.sql.sqltypes.AutoString(length=512),
            nullable=True,
        ),
        sa.Column(
            "file_path", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False
        ),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column(
            "fingerprint", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False
        ),
        sa.Column(
            "severity", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column(
            "category", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
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
        sa.ForeignKeyConstraint(
            ["scan_id"], ["terraform_scan.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["terraform_root_id"], ["terraform_root.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["rule_id"], ["rule.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "terraform_root_id",
            "fingerprint",
            name="uq_terraform_finding_root_fingerprint",
        ),
    )
    op.create_index(
        "ix_terraform_finding_fingerprint", "terraform_finding", ["fingerprint"]
    )
    op.create_index(
        "ix_terraform_finding_status", "terraform_finding", ["status"]
    )

    op.create_table(
        "cloud_account",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column(
            "provider", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column(
            "display_name",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column(
            "role_arn", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True
        ),
        sa.Column(
            "external_id",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=False,
        ),
        sa.Column(
            "regions", sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=False
        ),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="pending_verification",
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )

    op.create_table(
        "cloud_scan",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cloud_account_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column(
            "triggered_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column(
            "region", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True
        ),
        sa.Column("resource_count", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column(
            "grade", sqlmodel.sql.sqltypes.AutoString(length=8), nullable=True
        ),
        sa.Column(
            "artifact_object_key",
            sqlmodel.sql.sqltypes.AutoString(length=512),
            nullable=True,
        ),
        sa.Column(
            "error_message",
            sqlmodel.sql.sqltypes.AutoString(length=2048),
            nullable=True,
        ),
        sa.Column(
            "failure_kind", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["cloud_account_id"], ["cloud_account.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "cloud_finding",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("cloud_account_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column(
            "resource_type",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column(
            "resource_id",
            sqlmodel.sql.sqltypes.AutoString(length=1024),
            nullable=False,
        ),
        sa.Column(
            "region", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True
        ),
        sa.Column(
            "fingerprint", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False
        ),
        sa.Column(
            "severity", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column(
            "category", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
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
        sa.ForeignKeyConstraint(["scan_id"], ["cloud_scan.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["cloud_account_id"], ["cloud_account.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["rule_id"], ["rule.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "cloud_account_id",
            "fingerprint",
            name="uq_cloud_finding_account_fingerprint",
        ),
    )
    op.create_index("ix_cloud_finding_fingerprint", "cloud_finding", ["fingerprint"])
    op.create_index("ix_cloud_finding_status", "cloud_finding", ["status"])


def downgrade() -> None:
    op.drop_index("ix_cloud_finding_status", table_name="cloud_finding")
    op.drop_index("ix_cloud_finding_fingerprint", table_name="cloud_finding")
    op.drop_table("cloud_finding")
    op.drop_table("cloud_scan")
    op.drop_table("cloud_account")

    op.drop_index("ix_terraform_finding_status", table_name="terraform_finding")
    op.drop_index(
        "ix_terraform_finding_fingerprint", table_name="terraform_finding"
    )
    op.drop_table("terraform_finding")
    op.drop_table("terraform_scan")
    op.drop_table("terraform_root")

    op.drop_column("rule", "domain")
