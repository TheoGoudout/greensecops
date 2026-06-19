"""Make installation_id nullable on repository

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-18

"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "repository",
        "installation_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "repository",
        "installation_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
