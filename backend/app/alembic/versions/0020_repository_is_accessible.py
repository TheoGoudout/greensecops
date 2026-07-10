"""Add is_accessible to repository

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "repository",
        sa.Column("is_accessible", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("repository", "is_accessible")
