"""Drop diff column from fix table

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("fix", "diff")


def downgrade() -> None:
    op.add_column("fix", sa.Column("diff", sa.Text(), nullable=True))
