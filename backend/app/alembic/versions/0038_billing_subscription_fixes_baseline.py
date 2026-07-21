"""Add billing_subscription.fixes_used_baseline

Revision ID: 0038
Revises: 0037
Create Date: 2026-07-20

Usage now resets monthly instead of accumulating forever. Analyses are
filtered directly by timestamp; fixes are billed from a lifetime counter that
must stay monotonic (WorkflowFile.fix_generation_count survives regenerate),
so period usage is instead derived as lifetime_sum - fixes_used_baseline,
where the baseline is snapshotted each time the period rolls over.
"""

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "billing_subscription",
        sa.Column(
            "fixes_used_baseline",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("billing_subscription", "fixes_used_baseline")
