"""Add issue.needs_manual_work and issue.manual_work_note

Revision ID: 0038
Revises: 0037
Create Date: 2026-07-20

Fix-generation now asks the LLM to report, in the same call, which of the
issues it was given it could not resolve in the workflow-file diff. Those
issues are flagged here instead of silently being counted as "fixed" in the
PR body.
"""

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "issue",
        sa.Column(
            "needs_manual_work",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "issue",
        sa.Column("manual_work_note", sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("issue", "manual_work_note")
    op.drop_column("issue", "needs_manual_work")
