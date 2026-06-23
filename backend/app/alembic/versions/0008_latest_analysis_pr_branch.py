"""Add latest_analysis_id to workflow_file and pr_branch to fix

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-23

"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fix",
        sa.Column("pr_branch", sa.String(length=255), nullable=True),
    )

    op.add_column(
        "workflow_file",
        sa.Column("latest_analysis_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_wf_latest_analysis",
        "workflow_file",
        "analysis",
        ["latest_analysis_id"],
        ["id"],
        use_alter=True,
    )

    # Backfill: point each workflow_file at its most recent completed analysis.
    op.execute(
        """
        UPDATE workflow_file wf
        SET latest_analysis_id = sub.id
        FROM (
            SELECT DISTINCT ON (workflow_file_id) id, workflow_file_id
            FROM analysis
            WHERE status = 'completed'
            ORDER BY workflow_file_id, created_at DESC
        ) sub
        WHERE wf.id = sub.workflow_file_id
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_wf_latest_analysis", "workflow_file", type_="foreignkey")
    op.drop_column("workflow_file", "latest_analysis_id")
    op.drop_column("fix", "pr_branch")
