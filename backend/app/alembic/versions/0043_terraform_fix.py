"""Add Terraform fix → PR pipeline

Revision ID: 0043
Revises: 0042
Create Date: 2026-07-25

Adds the ``terraform_fix`` table (the Terraform analogue of ``fix``, keyed to
a ``(terraform_root_id, file_path)`` pair rather than a workflow file) and a
nullable ``terraform_finding.fix_id`` linking a finding to the fix that
addresses it — mirrors ``issue.fix_id``. Terraform fixes are delivered as PRs
reusing the existing repo-scoped ``pull_request`` table (no schema change
there).
"""

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "terraform_fix",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("terraform_root_id", sa.Uuid(), nullable=False),
        sa.Column(
            "file_path", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False
        ),
        sa.Column("pr_id", sa.Uuid(), nullable=True),
        sa.Column(
            "llm_provider", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column(
            "llm_model", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "langsmith_run_id",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("full_content", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            "error_message",
            sqlmodel.sql.sqltypes.AutoString(length=2048),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["terraform_root_id"], ["terraform_root.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["pr_id"], ["pull_request.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "terraform_root_id", "file_path", name="uq_terraform_fix_root_file"
        ),
    )
    op.add_column(
        "terraform_finding",
        sa.Column("fix_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_terraform_finding_fix_id",
        "terraform_finding",
        "terraform_fix",
        ["fix_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_terraform_finding_fix_id", "terraform_finding", type_="foreignkey"
    )
    op.drop_column("terraform_finding", "fix_id")
    op.drop_table("terraform_fix")
