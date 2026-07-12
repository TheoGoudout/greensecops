"""Add a persisted issue.status column maintained by a trigger

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-12

Issue status is derived from ``resolved_at`` and ``fix_id``. Persisting it as a
column (rather than computing it in Python) makes it queryable/indexable, and a
BEFORE INSERT OR UPDATE trigger keeps it authoritative — including when
``fix_id`` is cleared by the ``ON DELETE SET NULL`` cascade on fix deletion,
which bypasses application code.
"""

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


_COMPUTE_FN = """
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

_TRIGGER = """
CREATE TRIGGER issue_status_trg
BEFORE INSERT OR UPDATE ON issue
FOR EACH ROW EXECUTE FUNCTION issue_compute_status();
"""


def upgrade() -> None:
    op.add_column(
        "issue",
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="open",
        ),
    )
    op.create_index("ix_issue_status", "issue", ["status"])
    # Backfill from the existing derived fields.
    op.execute(
        """
        UPDATE issue SET status = CASE
            WHEN resolved_at IS NOT NULL THEN 'resolved'
            WHEN fix_id IS NOT NULL THEN 'fix_in_progress'
            ELSE 'open'
        END
        """
    )
    op.execute(_COMPUTE_FN)
    op.execute(_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS issue_status_trg ON issue")
    op.execute("DROP FUNCTION IF EXISTS issue_compute_status()")
    op.drop_index("ix_issue_status", table_name="issue")
    op.drop_column("issue", "status")
