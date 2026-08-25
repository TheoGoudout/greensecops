"""Rename the rule domain 'workflow' to 'ci_workflow'

Every ``RuleDomain`` member is a directory name under ``app/rules/`` — except
this one, which was ``workflow`` against a ``ci_workflow/`` directory. Bridging
the two took a hand-maintained ``_RULES_DIR_TO_DOMAIN`` table in
``core/rule_registry`` whose only guarantee was a comment, and which had to gain
a row every time an engine was added. Renaming the value makes the mapping an
identity, so the table is deleted and the domain is derived with
``RuleDomain(dir_name)``.

``domain`` is a plain varchar rather than a Postgres enum, so this is an UPDATE
plus a server-default swap — no type surgery. The ``uq_rule_domain_slug``
constraint is unaffected: no ``ci_workflow`` rows exist to collide with, and the
rename is order-independent within one statement.

Revision ID: 0052
Revises: 0051
"""

from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None

_OLD = "workflow"
_NEW = "ci_workflow"


def upgrade() -> None:
    op.execute(f"UPDATE rule SET domain = '{_NEW}' WHERE domain = '{_OLD}'")
    op.alter_column("rule", "domain", server_default=_NEW)


def downgrade() -> None:
    op.execute(f"UPDATE rule SET domain = '{_OLD}' WHERE domain = '{_NEW}'")
    op.alter_column("rule", "domain", server_default=_OLD)
