"""Add workflow_file.fix_generation_count

Revision ID: 0037
Revises: 0036
Create Date: 2026-07-20

Persistent, cumulative counter of AI fix generations (initial + regenerate)
for a workflow file. Fix rows are deleted and recreated on regenerate, so a
live-row count under-reports usage — this counter survives that delete and
gives billing a true count of billable generation events. Backfilled to 1
for workflow files that already carry a live fix, so existing usage doesn't
drop to zero for orgs that already generated fixes before this migration.
"""

import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_file",
        sa.Column(
            "fix_generation_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.execute(
        "UPDATE workflow_file SET fix_generation_count = 1 "
        "WHERE id IN (SELECT workflow_file_id FROM fix)"
    )


def downgrade() -> None:
    op.drop_column("workflow_file", "fix_generation_count")
