"""Backfill issue.workflow_file_id from analysis.workflow_file_id

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-01
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE issue
            SET workflow_file_id = analysis.workflow_file_id
            FROM analysis
            WHERE issue.analysis_id = analysis.id
              AND issue.workflow_file_id IS NULL
            """
        )
    )


def downgrade() -> None:
    pass
