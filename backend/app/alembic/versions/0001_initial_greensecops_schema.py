"""Initial GreenSecOps schema

Revision ID: 0001
Revises:
Create Date: 2026-06-10

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # user table
    op.create_table(
        "user",
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("full_name", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("github_id", sa.Integer(), nullable=True),
        sa.Column("github_username", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("tier", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="free"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hashed_password", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_email"), "user", ["email"], unique=True)
    op.create_index(op.f("ix_user_github_id"), "user", ["github_id"], unique=True)

    # organization table
    op.create_table(
        "organization",
        sa.Column("github_org_id", sa.Integer(), nullable=True),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("tier", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="free"),
        sa.Column("default_llm_provider", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="openai"),
        sa.Column("default_llm_model", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("fix_delivery_mode", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="pr"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_organization_github_org_id"), "organization", ["github_org_id"], unique=True)
    op.create_index(op.f("ix_organization_name"), "organization", ["name"], unique=False)

    # org_member table
    op.create_table(
        "org_member",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="member"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id", "user_id"),
    )

    # repository table
    op.create_table(
        "repository",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("github_repo_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("default_branch", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False, server_default="main"),
        sa.Column("fix_delivery_mode", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("llm_provider", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("llm_model", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_repository_full_name"), "repository", ["full_name"], unique=False)
    op.create_index(op.f("ix_repository_github_repo_id"), "repository", ["github_repo_id"], unique=True)
    op.create_index(op.f("ix_repository_installation_id"), "repository", ["installation_id"], unique=False)

    # workflow_file table
    op.create_table(
        "workflow_file",
        sa.Column("repo_id", sa.Uuid(), nullable=False),
        sa.Column("path", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False),
        sa.Column("content_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("raw_content", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["repo_id"], ["repository.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workflow_file_content_hash"), "workflow_file", ["content_hash"], unique=False)

    # rule table
    op.create_table(
        "rule",
        sa.Column("slug", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("severity", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(length=2048), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("severity_weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_rule_slug"), "rule", ["slug"], unique=True)

    # analysis table
    op.create_table(
        "analysis",
        sa.Column("repo_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_file_id", sa.Uuid(), nullable=False),
        sa.Column("content_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="pending"),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("grade", sqlmodel.sql.sqltypes.AutoString(length=8), nullable=True),
        sa.Column("triggered_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="manual"),
        sa.Column("branch", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("commit_sha", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column("error_message", sqlmodel.sql.sqltypes.AutoString(length=2048), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["repo_id"], ["repository.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_file_id"], ["workflow_file.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_analysis_content_hash"), "analysis", ["content_hash"], unique=False)

    # issue table
    op.create_table(
        "issue",
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("severity", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("message", sqlmodel.sql.sqltypes.AutoString(length=2048), nullable=False),
        sa.Column("context", sqlmodel.sql.sqltypes.AutoString(length=4096), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["analysis_id"], ["analysis.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["rule.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    # fix table
    op.create_table(
        "fix",
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("llm_provider", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("llm_model", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("langsmith_run_id", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="pending"),
        sa.Column("diff", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("pr_url", sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=True),
        sa.Column("comment_url", sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=True),
        sa.Column("error_message", sqlmodel.sql.sqltypes.AutoString(length=2048), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["issue_id"], ["issue.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("issue_id"),
        sa.PrimaryKeyConstraint("id"),
    )

    # telemetry_run table
    op.create_table(
        "telemetry_run",
        sa.Column("repo_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Integer(), nullable=False),
        sa.Column("runner_specs", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("metrics", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["repo_id"], ["repository.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_telemetry_run_workflow_run_id"), "telemetry_run", ["workflow_run_id"], unique=False)

    # billing_subscription table
    op.create_table(
        "billing_subscription",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tier", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="free"),
        sa.Column("stripe_subscription_id", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("stripe_customer_id", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("analyses_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fixes_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id"),
        sa.UniqueConstraint("stripe_subscription_id"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("billing_subscription")
    op.drop_table("telemetry_run")
    op.drop_table("fix")
    op.drop_table("issue")
    op.drop_index(op.f("ix_analysis_content_hash"), table_name="analysis")
    op.drop_table("analysis")
    op.drop_index(op.f("ix_rule_slug"), table_name="rule")
    op.drop_table("rule")
    op.drop_index(op.f("ix_workflow_file_content_hash"), table_name="workflow_file")
    op.drop_table("workflow_file")
    op.drop_index(op.f("ix_repository_installation_id"), table_name="repository")
    op.drop_index(op.f("ix_repository_github_repo_id"), table_name="repository")
    op.drop_index(op.f("ix_repository_full_name"), table_name="repository")
    op.drop_table("repository")
    op.drop_table("org_member")
    op.drop_index(op.f("ix_organization_name"), table_name="organization")
    op.drop_index(op.f("ix_organization_github_org_id"), table_name="organization")
    op.drop_table("organization")
    op.drop_index(op.f("ix_user_github_id"), table_name="user")
    op.drop_index(op.f("ix_user_email"), table_name="user")
    op.drop_table("user")
