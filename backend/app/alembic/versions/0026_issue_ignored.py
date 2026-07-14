"""Add issue.ignored_at and fold `ignored` into the status trigger

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-13

A user can dismiss a violation (false positive / accepted risk) by setting
``issue.ignored_at``. The status column (migration 0022) is extended so a row
with ``ignored_at`` set reads ``ignored``, taking precedence over resolve/fix
activity. The status column is a plain string, so only the trigger function
changes; no enum type migration is needed.
"""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


# ``ignored`` wins over every other state: a muted violation stays muted
# regardless of fix_id / resolved_at.
_COMPUTE_FN_V2 = """
CREATE OR REPLACE FUNCTION issue_compute_status() RETURNS trigger AS $$
BEGIN
    IF NEW.ignored_at IS NOT NULL THEN
        NEW.status := 'ignored';
    ELSIF NEW.resolved_at IS NOT NULL THEN
        NEW.status := 'resolved';
    ELSIF NEW.fix_id IS NOT NULL THEN
        NEW.status := 'fix_in_progress';
    ELSE
        NEW.status := 'open';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# The original 0022 function, restored on downgrade.
_COMPUTE_FN_V1 = """
CREATE OR REPLACE FUNCTION issue_compute_status() RETURNS trigger AS $$
BEGIN
    IF NEW.resolved_at IS NOT NULL THEN
        NEW.status := 'resolved';
    ELSIF NEW.fix_id IS NOT NULL THEN
        NEW.status := 'fix_in_progress';
    ELSE
        NEW.status := 'open';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.add_column(
        "issue",
        sa.Column("ignored_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(_COMPUTE_FN_V2)
    # Recompute existing rows through the new function (the trigger fires on
    # UPDATE); a no-op self-update is enough to reclassify any that would now
    # read ``ignored`` — none exist yet, but this keeps the column authoritative.
    op.execute("UPDATE issue SET ignored_at = ignored_at")


def downgrade() -> None:
    op.execute(_COMPUTE_FN_V1)
    op.execute("UPDATE issue SET status = status WHERE ignored_at IS NOT NULL")
    op.drop_column("issue", "ignored_at")
