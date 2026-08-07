"""Index every scan table on (target, recency) for latest-scan lookups

"What is this target's most recent scan?" is the question behind a target's
grade, and every engine answers it the same way: filter by the target FK, order
by recency, take one. Until now no scan table had an index on that pair —
Postgres does not index foreign keys automatically — so each answer meant a
sequential scan plus a sort.

That was already being paid for on every dashboard load by the ``latest_only``
subquery in ``GET /issues/stats``, and the new ``GET /overview/`` makes it
sharper still: its coverage query runs a ``row_number() OVER (PARTITION BY
<target_fk> ORDER BY <recency>)`` over each of the four scan tables, which is
exactly the access pattern these indexes serve.

The recency column differs by engine, matching the ordering each engine's own
endpoints already use: ``analysis`` orders by ``completed_at`` then
``created_at`` (as ``get_issue_stats`` does), the three newer engines by
``created_at`` alone (as ``mappers/base.latest_completed_scan`` does).

Pure index additions — no column or data changes, and ``downgrade`` simply
drops them.

Revision ID: 0051
Revises: 0050
"""

from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None

# (index name, table, columns). DESC on the recency columns so the index is
# already in the order the window function and the LIMIT 1 subqueries want.
_INDEXES = [
    (
        "ix_analysis_workflow_file_recency",
        "analysis",
        ["workflow_file_id", "completed_at DESC", "created_at DESC"],
    ),
    (
        "ix_docker_scan_target_created",
        "docker_scan",
        ["docker_target_id", "created_at DESC"],
    ),
    (
        "ix_terraform_scan_root_created",
        "terraform_scan",
        ["terraform_root_id", "created_at DESC"],
    ),
    (
        "ix_cloud_scan_account_created",
        "cloud_scan",
        ["cloud_account_id", "created_at DESC"],
    ),
]


def upgrade() -> None:
    for name, table, columns in _INDEXES:
        # Raw SQL rather than op.create_index: the DESC modifiers are part of
        # the index definition and op.create_index has no way to express them.
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({', '.join(columns)})"
        )


def downgrade() -> None:
    for name, _table, _columns in reversed(_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name}")
