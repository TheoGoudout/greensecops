"""Add workflow_file.deleted_at

Revision ID: 0041
Revises: 0040
Create Date: 2026-07-21

Soft-delete marker for a workflow file. When a `.github/workflows/*.yml` path
disappears from its branch, the row is flagged (rather than hard-deleted, which
would cascade away its Analysis/Issue history) so it stops showing up in the
static-analysis view and repo grade. NULL means the file is still present;
existing rows stay NULL. Cleared when the same path reappears.
"""

import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_file",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("workflow_file", "deleted_at")
