"""Backfill legacy NULL pull_request.pr_state and make it NOT NULL

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-13

``pull_request.pr_state`` was nullable; legacy rows carry ``NULL``, and every
state-machine ``try_advance`` on such a row silently no-ops, so merges/closes on
old PRs were never recorded. Backfill ``NULL`` rows to ``open`` (conservative —
the ``sync_open_pr_states`` maintenance task reconciles genuinely merged/closed
PRs against GitHub on its next run) and make the column NOT NULL with an
``open`` default so new rows can never regress to ``NULL``.
"""

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE pull_request SET pr_state = 'open' WHERE pr_state IS NULL")
    op.alter_column(
        "pull_request",
        "pr_state",
        existing_type=sa.String(),
        nullable=False,
        server_default="open",
    )


def downgrade() -> None:
    op.alter_column(
        "pull_request",
        "pr_state",
        existing_type=sa.String(),
        nullable=True,
        server_default=None,
    )
