"""Remove pr_url/pr_branch/pr_state/comment_url from fix table

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-30
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("fix", "pr_url")
    op.drop_column("fix", "pr_branch")
    op.drop_column("fix", "pr_state")
    op.drop_column("fix", "comment_url")


def downgrade() -> None:
    op.add_column("fix", sa.Column("pr_url", sa.String(1024), nullable=True))
    op.add_column("fix", sa.Column("pr_branch", sa.String(255), nullable=True))
    op.add_column("fix", sa.Column("pr_state", sa.String(32), nullable=True))
    op.add_column("fix", sa.Column("comment_url", sa.String(1024), nullable=True))
