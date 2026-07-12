"""Drop never-persisted analysis states (pending, skipped)

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-12

``AnalysisStatus`` no longer includes ``pending`` or ``skipped``: rows are
created directly as ``running``/``no_workflows``, and content-hash duplicates
reference the prior analysis instead of writing a ``skipped`` row. The status
column is a plain string, so this only needs a defensive remap of any stray
rows and a server-default change (``pending`` -> ``running``).
"""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Defensive: no such rows are expected (these states were never written),
    # but map any strays to their terminal equivalents so no invalid value
    # lingers. A stuck 'pending' is a never-run analysis -> failed.
    op.execute("UPDATE analysis SET status = 'failed' WHERE status = 'pending'")
    op.execute("UPDATE analysis SET status = 'completed' WHERE status = 'skipped'")
    op.alter_column("analysis", "status", server_default="running")


def downgrade() -> None:
    op.alter_column("analysis", "status", server_default="pending")
