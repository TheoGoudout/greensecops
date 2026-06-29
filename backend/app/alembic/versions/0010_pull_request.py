"""Add pull_request table and patch/pr_id to fix

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-29

"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pull_request",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("pr_branch", sa.String(255), nullable=False),
        sa.Column("pr_url", sa.String(1024), nullable=True),
        sa.Column("pr_state", sa.String(32), nullable=True),
        sa.Column("comment_url", sa.String(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["repo_id"], ["repository.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("repo_id", "pr_branch", name="uq_pr_repo_branch"),
    )
    op.create_index("ix_pull_request_pr_branch", "pull_request", ["pr_branch"])

    op.add_column("fix", sa.Column("patch", sa.Text(), nullable=True))
    op.add_column("fix", sa.Column("pr_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_fix_pull_request",
        "fix",
        "pull_request",
        ["pr_id"],
        ["id"],
        ondelete="SET NULL",
    )

    bind = op.get_bind()

    # Backfill pull_request rows from existing delivered fixes
    rows = bind.execute(
        text(
            """
            SELECT DISTINCT ON (f.pr_branch, a.repo_id)
                   a.repo_id,
                   f.pr_branch,
                   f.pr_url,
                   f.pr_state,
                   f.comment_url
            FROM fix f
            JOIN issue i ON i.id = f.issue_id
            JOIN analysis a ON a.id = i.analysis_id
            WHERE f.pr_branch IS NOT NULL
            ORDER BY f.pr_branch, a.repo_id, f.delivered_at DESC NULLS LAST
            """
        )
    ).fetchall()

    pr_map: dict[tuple, str] = {}
    for repo_id, pr_branch, pr_url, pr_state, comment_url in rows:
        pr_id = str(uuid.uuid4())
        pr_map[(str(repo_id), pr_branch)] = pr_id
        bind.execute(
            text(
                """
                INSERT INTO pull_request (id, repo_id, pr_branch, pr_url, pr_state, comment_url)
                VALUES (:id, :repo_id, :pr_branch, :pr_url, :pr_state, :comment_url)
                """
            ),
            {
                "id": pr_id,
                "repo_id": str(repo_id),
                "pr_branch": pr_branch,
                "pr_url": pr_url,
                "pr_state": pr_state,
                "comment_url": comment_url,
            },
        )

    # Backfill fix.pr_id from the newly created pull_request rows
    if pr_map:
        fix_rows = bind.execute(
            text(
                """
                SELECT f.id, a.repo_id, f.pr_branch
                FROM fix f
                JOIN issue i ON i.id = f.issue_id
                JOIN analysis a ON a.id = i.analysis_id
                WHERE f.pr_branch IS NOT NULL
                """
            )
        ).fetchall()
        for fix_id, repo_id, pr_branch in fix_rows:
            pr_id = pr_map.get((str(repo_id), pr_branch))
            if pr_id:
                bind.execute(
                    text("UPDATE fix SET pr_id = :pr_id WHERE id = :fix_id"),
                    {"pr_id": pr_id, "fix_id": str(fix_id)},
                )


def downgrade() -> None:
    op.drop_constraint("fk_fix_pull_request", "fix", type_="foreignkey")
    op.drop_column("fix", "pr_id")
    op.drop_column("fix", "patch")
    op.drop_index("ix_pull_request_pr_branch", table_name="pull_request")
    op.drop_table("pull_request")
