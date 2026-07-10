"""Add no_workflows analysis status; make workflow_file_id nullable

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("analysis", "workflow_file_id", nullable=True)


def downgrade() -> None:
    # Rows with no_workflows status have workflow_file_id = NULL; delete them
    # before restoring the NOT NULL constraint.
    op.execute(
        "DELETE FROM analysis WHERE status = 'no_workflows'"
    )
    op.alter_column("analysis", "workflow_file_id", nullable=False)
