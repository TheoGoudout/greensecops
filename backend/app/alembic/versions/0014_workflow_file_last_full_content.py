"""Add last_full_content to workflow_file

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workflow_file", sa.Column("last_full_content", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("workflow_file", "last_full_content")
