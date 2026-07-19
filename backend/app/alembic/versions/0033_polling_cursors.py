"""Add polling cursors for external-repo reconciliation

Revision ID: 0033
Revises: 0032
Create Date: 2026-07-18

External repos receive no webhooks, so a poller reconciles their state against
the GitHub REST API. These cursor columns let the poller detect changes:

- ``repository.last_polled_head_sha`` / ``last_polled_at``: the default-branch
  head last seen; a change triggers a polled analysis (the ``push`` analogue).
- ``pull_request.head_sha``: the PR head last seen; a change means new commits
  (the ``synchronize`` analogue).
- ``pull_request.last_polled_comment_at``: the timestamp up to which
  ``/greensecops`` command comments have been processed.

All nullable with no backfill — a NULL cursor simply makes the first poll a
baseline (it records the current state without firing spurious events).
"""

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "repository",
        sa.Column("last_polled_head_sha", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "repository",
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "pull_request",
        sa.Column("head_sha", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "pull_request",
        sa.Column(
            "last_polled_comment_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("pull_request", "last_polled_comment_at")
    op.drop_column("pull_request", "head_sha")
    op.drop_column("repository", "last_polled_at")
    op.drop_column("repository", "last_polled_head_sha")
