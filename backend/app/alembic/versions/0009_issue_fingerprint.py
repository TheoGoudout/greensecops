"""Add fingerprint, job, step, workflow_file_id to issue

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-29

"""

import hashlib

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("issue", sa.Column("job", sa.String(255), nullable=True))
    op.add_column("issue", sa.Column("step", sa.String(255), nullable=True))
    op.add_column(
        "issue",
        sa.Column("workflow_file_id", sa.UUID(), nullable=True),
    )
    op.add_column("issue", sa.Column("fingerprint", sa.String(16), nullable=True))

    op.create_index("ix_issue_workflow_file_id", "issue", ["workflow_file_id"])
    op.create_index("ix_issue_fingerprint", "issue", ["fingerprint"])

    op.create_foreign_key(
        "fk_issue_workflow_file",
        "issue",
        "workflow_file",
        ["workflow_file_id"],
        ["id"],
        ondelete="CASCADE",
    )

    bind = op.get_bind()

    # Backfill workflow_file_id from analysis join
    bind.execute(
        text(
            """
            UPDATE issue i
            SET workflow_file_id = a.workflow_file_id
            FROM analysis a
            WHERE a.id = i.analysis_id
            """
        )
    )

    # Backfill fingerprint in Python (avoids pgcrypto dependency)
    rows = bind.execute(
        text(
            "SELECT id, workflow_file_id, rule_id FROM issue WHERE workflow_file_id IS NOT NULL"
        )
    ).fetchall()
    for row in rows:
        issue_id, wf_id, rule_id = row
        key = f"{wf_id}:{rule_id}::"
        fp = hashlib.sha256(key.encode()).hexdigest()[:16]
        bind.execute(
            text("UPDATE issue SET fingerprint = :fp WHERE id = :id"),
            {"fp": fp, "id": str(issue_id)},
        )

    # Remove duplicates: keep the issue with the most recent created_at per fingerprint
    bind.execute(
        text(
            """
            DELETE FROM issue
            WHERE id NOT IN (
                SELECT DISTINCT ON (workflow_file_id, fingerprint) id
                FROM issue
                WHERE fingerprint IS NOT NULL
                  AND workflow_file_id IS NOT NULL
                ORDER BY workflow_file_id, fingerprint, created_at DESC NULLS LAST
            )
            AND fingerprint IS NOT NULL
            AND workflow_file_id IS NOT NULL
            """
        )
    )

    op.create_unique_constraint(
        "uq_issue_wf_fingerprint",
        "issue",
        ["workflow_file_id", "fingerprint"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_issue_wf_fingerprint", "issue", type_="unique")
    op.drop_constraint("fk_issue_workflow_file", "issue", type_="foreignkey")
    op.drop_index("ix_issue_fingerprint", table_name="issue")
    op.drop_index("ix_issue_workflow_file_id", table_name="issue")
    op.drop_column("issue", "fingerprint")
    op.drop_column("issue", "workflow_file_id")
    op.drop_column("issue", "step")
    op.drop_column("issue", "job")
