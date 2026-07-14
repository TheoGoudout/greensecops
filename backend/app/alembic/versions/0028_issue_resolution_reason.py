"""Add issue.resolution_reason

Revision ID: 0028
Revises: 0027
Create Date: 2026-07-14

Records *why* an issue resolved (no_longer_detected / file_removed / merged) as
an attribute of the ``resolved`` state, avoiding a split of ``resolved`` into
several states. Plain nullable string column (enum stored as text).
"""

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "issue",
        sa.Column("resolution_reason", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("issue", "resolution_reason")
