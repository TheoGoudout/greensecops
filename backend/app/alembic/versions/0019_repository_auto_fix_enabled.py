"""Add auto_fix_enabled to repository

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "repository",
        sa.Column("auto_fix_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("repository", "auto_fix_enabled")
