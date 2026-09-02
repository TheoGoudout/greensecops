"""Add rule.remediation

Revision ID: 0057
Revises: 0056
Create Date: 2026-09-02

Every Rego policy carries a ``custom.examples.fix`` block — the rule author's
own remediation prose, complete with the caveats that make the fix correct
("with a tmpfs for the paths the process genuinely writes", "use paths-ignore
where a required status check is involved"). Until now it reached the docs and
nothing else: the fix prompts sent the model a one-line finding message and let
it reinvent the remediation, which is how bare ``read_only: true`` landed on a
postgres service and plain ``paths:`` filters landed on required checks.

Nullable because rows seeded before this column existed have no value until the
next boot re-seeds them; ``app.core.rule_registry`` requires the METADATA block
of every shipped rule, so a fresh catalog is always fully populated.
"""

import sqlalchemy as sa
from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rule",
        sa.Column("remediation", sa.String(length=2048), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rule", "remediation")
