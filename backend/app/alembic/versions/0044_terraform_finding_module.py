"""Add module_path/terraform_address to terraform_finding

Revision ID: 0044
Revises: 0043
Create Date: 2026-07-27

Adds two nullable columns to ``terraform_finding`` so a finding carries its
module locator and full Terraform address alongside the file/line span:

- ``module_path`` — directory-derived module locator (e.g. ``modules/storage``),
  null for root-module resources and JSON-config files.
- ``terraform_address`` — the full address
  (``module.modules.storage.aws_s3_bucket.logs``), or the bare resource address
  at the root.

See ``services/terraform/hcl_parser.derive_module_path`` — a path heuristic, not
a resolved ``module {}`` invocation chain.
"""

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "terraform_finding",
        sa.Column(
            "module_path",
            sqlmodel.sql.sqltypes.AutoString(length=512),
            nullable=True,
        ),
    )
    op.add_column(
        "terraform_finding",
        sa.Column(
            "terraform_address",
            sqlmodel.sql.sqltypes.AutoString(length=1024),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("terraform_finding", "terraform_address")
    op.drop_column("terraform_finding", "module_path")
