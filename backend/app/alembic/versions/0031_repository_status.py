"""Add repository.status (accessibility/lifecycle machine)

Revision ID: 0031
Revises: 0030
Create Date: 2026-07-14

Formalises the accessibility axis as a ``RepositoryStatus`` column driven by the
RepositoryMachine. ``is_accessible`` becomes a machine-synced cache of
``status == active``; ``enabled``/``is_external`` stay independent flags.

Backfill: an inaccessible repo (``is_accessible = false``) maps to
``inaccessible``; everything else to ``active``. ``archived``/``suspended`` are
not retroactively distinguishable from historical flags, but the next relevant
webhook reclassifies them, and both are already inaccessible.
"""

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "repository",
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
        ),
    )
    op.execute(
        "UPDATE repository SET status = 'inaccessible' WHERE is_accessible = false"
    )


def downgrade() -> None:
    op.drop_column("repository", "status")
