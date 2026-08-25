"""Record where a stored workflow snapshot and a generated fix came from

Revision ID: 0052
Revises: 0051
Create Date: 2026-08-24

Three columns, all provenance for content we already store.

`workflow_file.source_commit_sha` is the commit `raw_content` was read at.
Until now nothing recorded it, so a stale snapshot was indistinguishable from a
fresh one and there was no cursor to order concurrent writes by. It pairs with
`workflow_file.fetched_at`, which the application never wrote after row
creation and now refreshes on every sync.

`fix.base_content` is the file content a rewrite was generated *from*, and
`fix.base_commit_sha` the commit it came from. A fix replaces the whole file,
so it is only meaningful against its own base; delivery's freshness check and
the UI diff both used to read `workflow_file.raw_content`, a different snapshot
from the one generation actually used.

All nullable with no server default and no backfill. NULL is the honest value
for a row written before this migration: `source_commit_sha` fills in on the
row's next sync, and both readers of `base_content` fall back to
`workflow_file.raw_content`, which reproduces the previous behaviour exactly.
That fallback is required anyway while old and new workers run side by side
during a rolling deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_file",
        sa.Column("source_commit_sha", sa.String(length=40), nullable=True),
    )
    # sa.Text() rather than the AutoString used by `full_content`: a whole
    # workflow file has no sensible length ceiling.
    op.add_column("fix", sa.Column("base_content", sa.Text(), nullable=True))
    op.add_column(
        "fix", sa.Column("base_commit_sha", sa.String(length=40), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("fix", "base_commit_sha")
    op.drop_column("fix", "base_content")
    op.drop_column("workflow_file", "source_commit_sha")
