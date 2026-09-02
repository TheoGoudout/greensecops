"""Add needs_manual_work / manual_work_note to the file-engine findings

Revision ID: 0058
Revises: 0057
Create Date: 2026-09-02

The fix generator asks every engine's LLM to report, in the same call, which of
the findings it was given it could not resolve — the ``<unfixed>`` block. The
CI-workflow engine has recorded that answer since migration 0038; the Docker,
Terraform and Ansible engines parsed it and threw it away, so those engines had
no way to decline a finding at all. A Docker fix that should have said "the
file's own comment says this USER is omitted deliberately" instead deleted the
comment and added the USER.

Same two columns, same shapes as ``workflow_finding`` — they now come from a
shared ``ManualWorkMixin``. ``cloud_finding`` is deliberately excluded: the
cloud engine has no files to rewrite and so no fixes to decline.
"""

import sqlalchemy as sa
from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None

_TABLES = ("docker_finding", "terraform_finding", "ansible_finding")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "needs_manual_work",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
        )
        op.add_column(
            table,
            sa.Column("manual_work_note", sa.String(length=1024), nullable=True),
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "manual_work_note")
        op.drop_column(table, "needs_manual_work")
