"""Fold AnalysisStatus into ScanStatus

``AnalysisStatus`` and ``ScanStatus`` were the same five-state lifecycle written
twice, differing in exactly one member: the CI engine spelled the empty case
``no_workflows`` where every other engine says ``no_targets``. That is
workflow-specific vocabulary for a case they all have — no ``.tf`` files under
this root, no resources of the scanned types in this account, no workflow files
in this repository — so the general spelling wins and the CI rows are rewritten.

``IssueStatus`` and ``IssueResolutionReason`` merge in the same commit but need
no data change: ``FindingStatus`` gained ``fix_in_progress`` and
``FindingResolutionReason`` gained ``file_removed``/``merged``/``branch_deleted``,
so every value already stored stays valid under the wider enum. Both columns are
varchar, not Postgres enums, so widening is a Python-side change only.

Revision ID: 0053
Revises: 0052
"""

from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE analysis SET status = 'no_targets' WHERE status = 'no_workflows'"
    )


def downgrade() -> None:
    # Only the CI engine's table is touched, so this cannot mistake a Terraform
    # or Docker scan's genuine `no_targets` for a renamed `no_workflows`.
    op.execute(
        "UPDATE analysis SET status = 'no_workflows' WHERE status = 'no_targets'"
    )
