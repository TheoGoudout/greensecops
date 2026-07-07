"""Add issue.resolved_at and fix.comment_url

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-07
"""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "issue", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "fix",
        sa.Column("comment_url", sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fix", "comment_url")
    op.drop_column("issue", "resolved_at")
