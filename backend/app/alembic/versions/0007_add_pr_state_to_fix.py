"""Add pr_state to fix

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-18

"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fix",
        sa.Column("pr_state", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fix", "pr_state")
