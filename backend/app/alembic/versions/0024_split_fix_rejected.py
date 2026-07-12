"""Split the overloaded fix `rejected` state

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-12

``FixStatus.rejected`` is replaced by two explicit states,
``rejected_by_user`` and ``superseded_by_closed_pr``, removing the previous
``delivered_at IS NULL`` convention used to tell them apart.

The status column is a plain string, so this is a data-only migration.
Existing ``rejected`` rows cannot be perfectly disambiguated after the fact
(both a user rejection of a ready fix and a guard rejection had
``delivered_at`` NULL), so they are conservatively mapped to
``rejected_by_user`` — the state that is *not* auto-restored on PR reopen.
Going forward the delivery guard writes ``superseded_by_closed_pr`` explicitly.
"""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE fix SET status = 'rejected_by_user' WHERE status = 'rejected'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE fix SET status = 'rejected' "
        "WHERE status IN ('rejected_by_user', 'superseded_by_closed_pr')"
    )
