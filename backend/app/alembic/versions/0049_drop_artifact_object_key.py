"""Drop the never-populated artifact_object_key columns

``terraform_scan.artifact_object_key`` and ``cloud_scan.artifact_object_key``
were added (0042) to hold an object-storage key for a scan's raw input — the
fetched ``.tf`` bundle and the normalized AWS resource snapshot — on the
assumption that both would grow too large for a Postgres column.

Neither was ever written. The scan workers pass their fetched input straight to
OPA and never persist it, so no row has ever had a non-NULL value here and no
code reads the columns. The object store they pointed at
(``services/storage/object_store.py``) had the same fate: its ``put_object`` /
``get_object`` were never called from anywhere, so the whole MinIO/S3 stack is
removed alongside this migration.

Reversible: ``downgrade`` restores both columns. They come back empty, which is
exactly the state they were in before, so nothing is lost by dropping them.

Revision ID: 0049
Revises: 0048
"""

import sqlalchemy as sa
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("terraform_scan", "artifact_object_key")
    op.drop_column("cloud_scan", "artifact_object_key")


def downgrade() -> None:
    op.add_column(
        "cloud_scan",
        sa.Column("artifact_object_key", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "terraform_scan",
        sa.Column("artifact_object_key", sa.String(length=512), nullable=True),
    )
