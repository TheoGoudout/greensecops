"""Add pull_request.externally_modified

Revision ID: 0034
Revises: 0033
Create Date: 2026-07-18

Set when a non-bot user pushes commits to a ``greensecops/*`` fix branch.
Auto-redelivery is blocked while the flag is set (it would overwrite the
user's edits); a successful forced delivery clears it. An attribute of the
PullRequest record, not a lifecycle state.
"""

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pull_request",
        sa.Column(
            "externally_modified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("pull_request", "externally_modified")
