"""Add analysis.failure_kind

Revision ID: 0029
Revises: 0028
Create Date: 2026-07-14

Distinguishes ``transient`` failures (safe to ``retry`` in place) from
``permanent`` ones (futile until the input changes). Plain nullable string
column (enum stored as text); only set when status is ``failed``.
"""

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analysis",
        sa.Column("failure_kind", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analysis", "failure_kind")
