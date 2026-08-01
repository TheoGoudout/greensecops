"""Add the Docker fix → PR pipeline

Split from 0045 the same way ``0043_terraform_fix`` was split from 0042: the
finding tables ship first and the fix pipeline lands on top, so the two can be
reviewed and rolled back independently.

``docker_finding.fix_id`` is added *after* ``docker_fix`` exists — the two
tables reference each other, so the FK is a second step.

No new ``pull_request`` column: ``docker_fix.pr_id`` points at the existing
table, exactly as ``terraform_fix.pr_id`` does.

Revision ID: 0046
Revises: 0045
"""

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "docker_fix",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("docker_target_id", sa.Uuid(), nullable=False),
        sa.Column(
            "file_path", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False
        ),
        sa.Column("pr_id", sa.Uuid(), nullable=True),
        sa.Column("llm_provider", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "llm_model", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "langsmith_run_id",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("full_content", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            "error_message",
            sqlmodel.sql.sqltypes.AutoString(length=2048),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["docker_target_id"], ["docker_target.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["pr_id"], ["pull_request.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "docker_target_id", "file_path", name="uq_docker_fix_target_file"
        ),
    )
    op.add_column("docker_finding", sa.Column("fix_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_docker_finding_fix_id",
        "docker_finding",
        "docker_fix",
        ["fix_id"],
        ["id"],
        # SET NULL: dropping a fix must not delete the finding's history.
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_docker_finding_fix_id", "docker_finding", type_="foreignkey"
    )
    op.drop_column("docker_finding", "fix_id")
    op.drop_table("docker_fix")
