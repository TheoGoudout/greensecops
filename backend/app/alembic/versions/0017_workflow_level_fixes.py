"""Restructure fix to one row per workflow file

Existing fix rows are discarded: fixes are now whole-file regenerations
and must be regenerated after this migration. Pull request records are kept.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-08
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM fix")

    op.drop_constraint("fix_issue_id_fkey", "fix", type_="foreignkey")
    op.drop_constraint("fix_issue_id_key", "fix", type_="unique")
    op.drop_column("fix", "issue_id")
    op.drop_column("fix", "patch")
    op.drop_column("fix", "comment_url")

    op.add_column("fix", sa.Column("workflow_file_id", sa.Uuid(), nullable=False))
    op.create_foreign_key(
        "fix_workflow_file_id_fkey",
        "fix",
        "workflow_file",
        ["workflow_file_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "fix_workflow_file_id_key", "fix", ["workflow_file_id"]
    )
    op.add_column("fix", sa.Column("full_content", sa.Text(), nullable=True))

    op.add_column("issue", sa.Column("fix_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "issue_fix_id_fkey",
        "issue",
        "fix",
        ["fix_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_column("workflow_file", "last_full_content")


def downgrade() -> None:
    op.add_column(
        "workflow_file", sa.Column("last_full_content", sa.Text(), nullable=True)
    )

    op.drop_constraint("issue_fix_id_fkey", "issue", type_="foreignkey")
    op.drop_column("issue", "fix_id")

    op.execute("DELETE FROM fix")
    op.drop_column("fix", "full_content")
    op.drop_constraint("fix_workflow_file_id_key", "fix", type_="unique")
    op.drop_constraint("fix_workflow_file_id_fkey", "fix", type_="foreignkey")
    op.drop_column("fix", "workflow_file_id")

    op.add_column("fix", sa.Column("issue_id", sa.Uuid(), nullable=False))
    op.create_foreign_key(
        "fix_issue_id_fkey", "fix", "issue", ["issue_id"], ["id"], ondelete="CASCADE"
    )
    op.create_unique_constraint("fix_issue_id_key", "fix", ["issue_id"])
    op.add_column("fix", sa.Column("patch", sa.Text(), nullable=True))
    op.add_column(
        "fix", sa.Column("comment_url", sa.String(length=1024), nullable=True)
    )
