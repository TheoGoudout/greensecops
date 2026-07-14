"""Add pull_request CI / review / mergeable attributes

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-14

CI outcome, latest review decision and GitHub mergeable_state as enrichment
attributes on the PR row (populated by check_suite / pull_request_review /
pull_request webhooks) rather than as extra machine states. The ``draft``
PullRequestState value needs no column (pr_state is a string). All nullable.
"""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pull_request",
        sa.Column("ci_status", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "pull_request",
        sa.Column("review_decision", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "pull_request",
        sa.Column("mergeable_state", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pull_request", "mergeable_state")
    op.drop_column("pull_request", "review_decision")
    op.drop_column("pull_request", "ci_status")
