"""Rename analysis/issue/fix to workflow_scan/workflow_finding/workflow_fix

The CI-workflow engine named its three tables ``analysis``, ``issue`` and
``fix``, while the Terraform, Docker and cloud engines name theirs
``<engine>_scan``, ``<engine>_finding`` and ``<engine>_fix``. Those are the same
three concepts, so the general nouns win and the CI engine joins the convention:
one vocabulary across the schema, and a reader who has learned one engine's
tables has learned them all.

Pure renaming. ``backend/scripts/schema_snapshot.py`` confirms that every
column's type, nullability, default, key and index is unchanged — the only
differences are the table names themselves and the foreign keys that point at
them.

Indexes and constraints are renamed alongside their tables. Postgres carries the
old names through ``ALTER TABLE ... RENAME``, so leaving them would give
``workflow_finding`` an index called ``ix_issue_status`` — exactly the kind of
half-renamed state that makes the next reader distrust the whole schema.

The ``issue_status_trg`` trigger and its ``issue_compute_status`` function are
recreated under the new names. The function body is unchanged from migration
0026: ``ignored`` still wins over every other state.

Revision ID: 0054
Revises: 0053
"""

from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None

_TABLES = [
    ("analysis", "workflow_scan"),
    ("issue", "workflow_finding"),
    ("fix", "workflow_fix"),
]

# (old, new) for everything that carries a table's name in its own.
_INDEXES = [
    ("ix_analysis_content_hash", "ix_workflow_scan_content_hash"),
    ("ix_analysis_workflow_file_recency", "ix_workflow_scan_workflow_file_recency"),
    ("ix_issue_fingerprint", "ix_workflow_finding_fingerprint"),
    ("ix_issue_status", "ix_workflow_finding_status"),
    ("ix_issue_workflow_file_id", "ix_workflow_finding_workflow_file_id"),
]

_CONSTRAINTS = [
    ("analysis", "analysis_pkey", "workflow_scan_pkey"),
    ("analysis", "analysis_repo_id_fkey", "workflow_scan_repo_id_fkey"),
    (
        "analysis",
        "analysis_workflow_file_id_fkey",
        "workflow_scan_workflow_file_id_fkey",
    ),
    ("issue", "issue_pkey", "workflow_finding_pkey"),
    ("issue", "issue_analysis_id_fkey", "workflow_finding_analysis_id_fkey"),
    ("issue", "issue_fix_id_fkey", "workflow_finding_fix_id_fkey"),
    ("issue", "issue_rule_id_fkey", "workflow_finding_rule_id_fkey"),
    ("issue", "fk_issue_workflow_file", "fk_workflow_finding_workflow_file"),
    ("issue", "uq_issue_wf_fingerprint", "uq_workflow_finding_wf_fingerprint"),
    ("fix", "fix_pkey", "workflow_fix_pkey"),
    ("fix", "fix_workflow_file_id_fkey", "workflow_fix_workflow_file_id_fkey"),
    ("fix", "fix_workflow_file_id_key", "workflow_fix_workflow_file_id_key"),
    ("fix", "fk_fix_pull_request", "fk_workflow_fix_pull_request"),
]

# `dynamic_enrichment.analysis_id` points at the renamed table but its own
# constraint is named after its column, which does not move — nothing to rename
# there. Listed as empty rather than omitted so the next reader can see it was
# considered.
_FOREIGN: list[tuple[str, str, str]] = []

_COMPUTE_FN = """
CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger AS $$
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

_TRIGGER = """
CREATE TRIGGER {trg}
BEFORE INSERT OR UPDATE OF ignored_at, resolved_at, fix_id ON {table}
FOR EACH ROW EXECUTE FUNCTION {fn}();
"""


def _swap(
    tables,
    indexes,
    constraints,
    foreign,
    old_trg,
    old_fn,
    old_table,
    new_trg,
    new_fn,
    new_table,
) -> None:
    # Drop the trigger first: it names the table it fires on, and recreating it
    # afterwards is simpler than teaching Postgres to follow the rename.
    op.execute(f"DROP TRIGGER IF EXISTS {old_trg} ON {old_table}")
    op.execute(f"DROP FUNCTION IF EXISTS {old_fn}()")

    for old, new in tables:
        op.execute(f"ALTER TABLE {old} RENAME TO {new}")
    for table, old, new in constraints:
        renamed = dict(tables)[table]
        op.execute(f"ALTER TABLE {renamed} RENAME CONSTRAINT {old} TO {new}")
    for old, new in indexes:
        op.execute(f"ALTER INDEX IF EXISTS {old} RENAME TO {new}")
    for table, old, new in foreign:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new}")

    op.execute(_COMPUTE_FN.format(fn=new_fn))
    op.execute(_TRIGGER.format(trg=new_trg, table=new_table, fn=new_fn))


def upgrade() -> None:
    _swap(
        _TABLES,
        _INDEXES,
        _CONSTRAINTS,
        _FOREIGN,
        old_trg="issue_status_trg",
        old_fn="issue_compute_status",
        old_table="issue",
        new_trg="workflow_finding_status_trg",
        new_fn="workflow_finding_compute_status",
        new_table="workflow_finding",
    )


def downgrade() -> None:
    _swap(
        [(new, old) for old, new in _TABLES],
        [(new, old) for old, new in _INDEXES],
        [
            (dict((o, n) for o, n in _TABLES)[t], new, old)
            for t, old, new in _CONSTRAINTS
        ],
        [(t, new, old) for t, old, new in _FOREIGN],
        old_trg="workflow_finding_status_trg",
        old_fn="workflow_finding_compute_status",
        old_table="workflow_finding",
        new_trg="issue_status_trg",
        new_fn="issue_compute_status",
        new_table="issue",
    )
