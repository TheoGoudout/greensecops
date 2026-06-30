"""Remove latest_analysis_id from workflow_file

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-30
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("fk_wf_latest_analysis", "workflow_file", type_="foreignkey")
    op.drop_column("workflow_file", "latest_analysis_id")


def downgrade() -> None:
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
