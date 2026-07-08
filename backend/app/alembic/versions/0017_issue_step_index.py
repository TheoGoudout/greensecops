"""Add step_index to issue

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-08

"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fingerprints are now keyed on the step's index within its job instead
    # of the action reference, so duplicate actions in one job no longer
    # collide. Existing rows keep their old-format fingerprints: the next
    # analysis run resolves them as stale and recreates issues under the new
    # scheme (their step index was never stored, so no backfill is possible).
    op.add_column("issue", sa.Column("step_index", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("issue", "step_index")
