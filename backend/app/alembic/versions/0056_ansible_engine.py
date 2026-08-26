"""Ansible engine: projects, scans, findings and fixes.

Revision ID: 0056
Revises: 0055
Create Date: 2026-08-25

The four tables the Ansible engine needs. The `iac_ansible` rules and their
`RuleDomain` member shipped earlier and needed no migration — `rule.domain` is
a plain varchar — so this is the first schema the engine has.

Enum columns are plain ``AutoString`` with raw-string server defaults rather
than Postgres ENUM types, matching every other engine's tables: adding a status
value later stays a code change instead of a migration. Autogenerate proposes
real ENUMs here; taking that offer would make these the only tables in the
schema that behave differently.

Kept as one revision rather than split the way ``0045``/``0046`` were for
Docker: those were split because the finding table shipped before the fix
pipeline existed. Here both arrive together, and ``ansible_finding.fix_id``
references ``ansible_fix``, so creating them apart would only mean adding the
column back in a second step.
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ansible_project",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repo_id", sa.Uuid(), nullable=False),
        sa.Column(
            "root_path", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "last_scanned_head_sha",
            sqlmodel.sql.sqltypes.AutoString(length=40),
            nullable=True,
        ),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["repo_id"], ["repository.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "repo_id", "root_path", name="uq_ansible_project_repo_path"
        ),
    )

    op.create_table(
        "ansible_scan",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ansible_project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("triggered_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("file_count", sa.Integer(), nullable=True),
        sa.Column("grade", sqlmodel.sql.sqltypes.AutoString(length=8), nullable=True),
        sa.Column(
            "error_message",
            sqlmodel.sql.sqltypes.AutoString(length=2048),
            nullable=True,
        ),
        sa.Column(
            "failure_kind", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True
        ),
        sa.Column("branch", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column(
            "commit_sha", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["ansible_project_id"], ["ansible_project.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "ansible_fix",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ansible_project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "file_path", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False
        ),
        sa.Column("pr_id", sa.Uuid(), nullable=True),
        sa.Column("llm_provider", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "llm_model", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "langsmith_run_id",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("full_content", sa.Text(), nullable=True),
        sa.Column(
            "error_message",
            sqlmodel.sql.sqltypes.AutoString(length=2048),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["ansible_project_id"], ["ansible_project.id"], ondelete="CASCADE"
        ),
        # SET NULL, not CASCADE: deleting a PR row must not take the fixes that
        # were delivered on it.
        sa.ForeignKeyConstraint(["pr_id"], ["pull_request.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ansible_project_id", "file_path", name="uq_ansible_fix_project_file"
        ),
    )

    op.create_table(
        "ansible_finding",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("ansible_project_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("fix_id", sa.Uuid(), nullable=True),
        sa.Column(
            "fingerprint", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False
        ),
        sa.Column("severity", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(),
            server_default="open",
            nullable=False,
        ),
        sa.Column(
            "message", sqlmodel.sql.sqltypes.AutoString(length=2048), nullable=False
        ),
        sa.Column(
            "context", sqlmodel.sql.sqltypes.AutoString(length=4096), nullable=True
        ),
        sa.Column(
            "file_path", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False
        ),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column(
            "task_name", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolution_reason",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
        ),
        sa.Column("ignored_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["ansible_project_id"], ["ansible_project.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["fix_id"], ["ansible_fix.id"], ondelete="SET NULL"),
        # RESTRICT: a rule with findings against it cannot be deleted out from
        # under them.
        sa.ForeignKeyConstraint(["rule_id"], ["rule.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["scan_id"], ["ansible_scan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ansible_project_id",
            "fingerprint",
            name="uq_ansible_finding_project_fingerprint",
        ),
    )
    op.create_index(
        "ix_ansible_finding_fingerprint", "ansible_finding", ["fingerprint"]
    )
    op.create_index("ix_ansible_finding_status", "ansible_finding", ["status"])

    # The latest-scan lookup every dashboard query makes, matching the indexes
    # 0051 added for the other engines. Raw SQL because op.create_index cannot
    # express the DESC modifier, which is what makes the index serve the
    # ordering rather than only the filter.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ansible_scan_project_created "
        "ON ansible_scan (ansible_project_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ansible_scan_project_created")
    op.drop_index("ix_ansible_finding_status", table_name="ansible_finding")
    op.drop_index("ix_ansible_finding_fingerprint", table_name="ansible_finding")
    op.drop_table("ansible_finding")
    op.drop_table("ansible_fix")
    op.drop_table("ansible_scan")
    op.drop_table("ansible_project")
