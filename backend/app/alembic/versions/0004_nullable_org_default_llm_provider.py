"""Make organization.default_llm_provider nullable

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-16

"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "organization",
        "default_llm_provider",
        existing_type=sa.String(),
        nullable=True,
        server_default=None,
    )


def downgrade() -> None:
    op.execute(
        "UPDATE organization SET default_llm_provider = 'openai' WHERE default_llm_provider IS NULL"
    )
    op.alter_column(
        "organization",
        "default_llm_provider",
        existing_type=sa.String(),
        nullable=False,
        server_default="openai",
    )
