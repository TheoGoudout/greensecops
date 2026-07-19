"""Add workflow_file.branch

Revision ID: 0034
Revises: 0033
Create Date: 2026-07-18

Workflow files (and the issues hanging off them) are now tracked per branch:
analyses run for pushes on any branch, and without a branch dimension a
feature-branch analysis would overwrite the default branch's content and
wrongly reconcile its issues. Existing rows are backfilled to the repository's
default branch. Plain string column (no enum).

The column goes straight to NOT NULL without a server default: prestart runs
migrations before the app starts and schema + code ship in the same deploy, so
no writer ever sees the column missing a value.

Before the new (repo_id, branch, path) unique constraint is created, any
pre-existing duplicate (repo_id, path) rows are collapsed defensively: the code
has always updated the first-found row under a per-repo lock, so duplicates are
not expected, but nothing enforced uniqueness at the schema level until now.
The newest-fetched row of each group is kept; analyses and non-colliding issues
are repointed to it, and the duplicate rows (with their fixes and colliding
issues) are deleted.
"""

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_file",
        sa.Column("branch", sa.String(length=255), nullable=True),
    )
    op.execute(
        """
        UPDATE workflow_file wf
        SET branch = r.default_branch
        FROM repository r
        WHERE wf.repo_id = r.id
        """
    )
    # Defensive dedupe of (repo_id, branch, path) groups. Keeper = newest
    # fetched_at (ties broken by id).
    op.execute(
        """
        CREATE TEMPORARY TABLE _wf_dupes ON COMMIT DROP AS
        SELECT id AS dupe_id,
               FIRST_VALUE(id) OVER (
                   PARTITION BY repo_id, branch, path
                   ORDER BY fetched_at DESC NULLS LAST, id
               ) AS keeper_id
        FROM workflow_file
        """
    )
    op.execute("DELETE FROM _wf_dupes WHERE dupe_id = keeper_id")
    op.execute(
        """
        UPDATE analysis a
        SET workflow_file_id = d.keeper_id
        FROM _wf_dupes d
        WHERE a.workflow_file_id = d.dupe_id
        """
    )
    # Issues on a duplicate row whose fingerprint already exists on the keeper
    # cannot be repointed (uq_issue_wf_fingerprint) — drop them.
    op.execute(
        """
        DELETE FROM issue i
        USING _wf_dupes d
        WHERE i.workflow_file_id = d.dupe_id
          AND EXISTS (
              SELECT 1 FROM issue k
              WHERE k.workflow_file_id = d.keeper_id
                AND k.fingerprint = i.fingerprint
          )
        """
    )
    op.execute(
        """
        UPDATE issue i
        SET workflow_file_id = d.keeper_id
        FROM _wf_dupes d
        WHERE i.workflow_file_id = d.dupe_id
        """
    )
    # fix.workflow_file_id is UNIQUE, so duplicate rows' fixes cannot be
    # repointed; deleting the duplicate workflow_file rows cascades them.
    op.execute(
        """
        DELETE FROM workflow_file wf
        USING _wf_dupes d
        WHERE wf.id = d.dupe_id
        """
    )
    op.alter_column("workflow_file", "branch", nullable=False)
    op.create_unique_constraint(
        "uq_workflow_file_repo_branch_path",
        "workflow_file",
        ["repo_id", "branch", "path"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_workflow_file_repo_branch_path", "workflow_file", type_="unique"
    )
    op.drop_column("workflow_file", "branch")
