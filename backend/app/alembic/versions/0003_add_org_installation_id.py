"""Add installation_id to Organization

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-12

"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organization",
        sa.Column("installation_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f("ix_organization_installation_id"),
        "organization",
        ["installation_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_organization_installation_id"),
        table_name="organization",
    )
    op.drop_column("organization", "installation_id")
