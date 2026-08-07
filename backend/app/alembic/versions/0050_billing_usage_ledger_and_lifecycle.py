"""Billing: usage ledger, subscription lifecycle, invoices, OSS applications

Three changes, all in service of billing measuring what the product actually
does.

**The usage ledger** (``billing_usage_record``) replaces the counters. Fix
usage used to be derived from ``workflow_file.fix_generation_count`` (a
lifetime, monotonic counter) minus ``billing_subscription.fixes_used_baseline``
(a snapshot taken at each period rollover). That trick worked for exactly one
engine. It cannot express a Terraform scan, it cannot say *what* consumed an
allowance, and it cannot be recomputed after a bug. The ledger is append-only
rows carrying their own ``occurred_at``, so a period is just a date range.

``billing_subscription.analyses_used`` and ``fixes_used`` are dropped as well:
both were written by nothing and read by nothing — every caller computed usage
on the fly — so they were columns that could only ever be wrong.

**The lifecycle columns** give a subscription a payment state alongside its
tier: ``status`` plus the grace-window bookkeeping the dunning task needs.
Existing rows become ``active``, which is what they effectively were.

**Invoices, OSS applications and webhook events** are new tables: billing
history that survives without Stripe, the review queue behind the pricing
page's "Apply for OSS plan" button, and the processed-event ids that make the
webhook idempotent under Stripe's retries.

## Backfill

Analyses are backfilled from the rows that already exist — every ``analysis``,
``terraform_scan``, ``docker_scan`` and ``cloud_scan``, dated by its own
``created_at`` and attributed to the org's billing owner. ``no_workflows`` and
``no_targets`` rows are excluded, matching the rule the application now
applies: nothing was evaluated, so nothing is charged.

Fix generations cannot be backfilled the same way. The lifetime counter carries
no timestamps, so there is no way to know which generations happened in which
month. Instead each subscription gets a single carry-over record dated at its
``period_start``, sized to exactly the fix usage the *old* formula would have
reported for the current period. Users see no jump on the day this ships, and
from here on every generation writes its own dated row.

Reversible: ``downgrade`` restores the dropped columns and recomputes
``fixes_used_baseline`` from the lifetime counters, which is the same value the
old code would have snapshotted. The ledger's history is lost on downgrade —
unavoidable, since there is nowhere in the old schema to put it.

Revision ID: 0050
Revises: 0049
"""

import sqlalchemy as sa
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Every status column in this schema is a VARCHAR, not a Postgres ENUM
    # type (SQLModel's default for these str-Enums, and the shape all 49 prior
    # migrations use). The new columns follow suit so the snapshot check in
    # ``scripts/schema_snapshot.py`` stays comparable.

    # ─── billing_subscription: lifecycle columns ─────────────────────────
    op.add_column(
        "billing_subscription",
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "billing_subscription",
        sa.Column("past_due_since", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "billing_subscription",
        sa.Column("grace_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "billing_subscription",
        sa.Column("dunning_stage", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "billing_subscription",
        sa.Column(
            "quota_warning_percent", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "billing_subscription",
        sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "billing_subscription",
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "billing_subscription",
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ─── The ledger ──────────────────────────────────────────────────────
    op.create_table(
        "billing_usage_record",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("repo_id", sa.Uuid(), nullable=True),
        sa.Column("meter", sa.String(length=16), nullable=False),
        sa.Column("engine", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repo_id"], ["repository.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_billing_usage_record_user_id", "billing_usage_record", ["user_id"]
    )
    # The only shape ever queried: one user's spend on one meter within a
    # period, so the range scan runs on a prefix match.
    op.create_index(
        "ix_billing_usage_record_user_meter_time",
        "billing_usage_record",
        ["user_id", "meter", "occurred_at"],
    )

    # ─── Invoices ────────────────────────────────────────────────────────
    op.create_table(
        "billing_invoice",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("stripe_invoice_id", sa.String(length=255), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="draft"
        ),
        sa.Column("amount_due_cents", sa.Integer(), nullable=False),
        sa.Column("amount_paid_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("number", sa.String(length=64), nullable=True),
        sa.Column("hosted_invoice_url", sa.String(length=1024), nullable=True),
        sa.Column("invoice_pdf", sa.String(length=1024), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["billing_subscription.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_billing_invoice_stripe_invoice_id",
        "billing_invoice",
        ["stripe_invoice_id"],
        unique=True,
    )

    # ─── Open-source applications ────────────────────────────────────────
    op.create_table(
        "billing_oss_application",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("repo_url", sa.String(length=512), nullable=False),
        sa.Column("license_name", sa.String(length=128), nullable=False),
        sa.Column("justification", sa.String(length=4096), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="pending"
        ),
        sa.Column("review_note", sa.String(length=2048), nullable=True),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_billing_oss_application_user_id", "billing_oss_application", ["user_id"]
    )

    # ─── Webhook idempotency ─────────────────────────────────────────────
    op.create_table(
        "billing_webhook_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("stripe_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_billing_webhook_event_stripe_event_id",
        "billing_webhook_event",
        ["stripe_event_id"],
        unique=True,
    )

    _backfill_ledger()

    # ─── Drop the superseded counters ────────────────────────────────────
    # Backfill first, then drop: fixes_used_baseline is an input to the
    # carry-over calculation above.
    op.drop_column("billing_subscription", "analyses_used")
    op.drop_column("billing_subscription", "fixes_used")
    op.drop_column("billing_subscription", "fixes_used_baseline")


# The billing owner of an org: its earliest-joined ``owner`` member, matching
# ``services/billing/owner.org_billing_owner``. Ties break on user_id so the
# result is stable rather than arbitrary.
_BILLING_OWNER = """
    SELECT DISTINCT ON (om.org_id) om.org_id, om.user_id
    FROM org_member om
    WHERE om.role = 'owner'
    ORDER BY om.org_id, om.joined_at, om.user_id
"""


def _backfill_ledger() -> None:
    """Seed the ledger from the rows that already exist.

    Analyses and scans carry their own ``created_at``, so they backfill exactly.
    Only rows attributable to a billing owner are inserted — an org with no
    owner member has nobody to charge, which is the same case the application
    treats as neither billed nor blocked.
    """
    op.execute(
        f"""
        WITH owner AS ({_BILLING_OWNER})
        INSERT INTO billing_usage_record
            (id, user_id, org_id, repo_id, meter, engine, quantity,
             source_type, source_id, occurred_at)
        SELECT gen_random_uuid(), owner.user_id, r.org_id, r.id,
               'analyses', 'workflow', 1, 'analysis', a.id,
               COALESCE(a.created_at, NOW())
        FROM analysis a
        JOIN repository r ON r.id = a.repo_id
        JOIN owner ON owner.org_id = r.org_id
        -- Nothing was evaluated for a no_workflows row, so it is not charged.
        WHERE a.status <> 'no_workflows'
        """
    )
    op.execute(
        f"""
        WITH owner AS ({_BILLING_OWNER})
        INSERT INTO billing_usage_record
            (id, user_id, org_id, repo_id, meter, engine, quantity,
             source_type, source_id, occurred_at)
        SELECT gen_random_uuid(), owner.user_id, r.org_id, r.id,
               'analyses', 'terraform', 1, 'terraform_scan', s.id,
               COALESCE(s.created_at, NOW())
        FROM terraform_scan s
        JOIN terraform_root t ON t.id = s.terraform_root_id
        JOIN repository r ON r.id = t.repo_id
        JOIN owner ON owner.org_id = r.org_id
        WHERE s.status <> 'no_targets'
        """
    )
    op.execute(
        f"""
        WITH owner AS ({_BILLING_OWNER})
        INSERT INTO billing_usage_record
            (id, user_id, org_id, repo_id, meter, engine, quantity,
             source_type, source_id, occurred_at)
        SELECT gen_random_uuid(), owner.user_id, r.org_id, r.id,
               'analyses', 'docker', 1, 'docker_scan', s.id,
               COALESCE(s.created_at, NOW())
        FROM docker_scan s
        JOIN docker_target t ON t.id = s.docker_target_id
        JOIN repository r ON r.id = t.repo_id
        JOIN owner ON owner.org_id = r.org_id
        WHERE s.status <> 'no_targets'
        """
    )
    op.execute(
        f"""
        WITH owner AS ({_BILLING_OWNER})
        INSERT INTO billing_usage_record
            (id, user_id, org_id, repo_id, meter, engine, quantity,
             source_type, source_id, occurred_at)
        SELECT gen_random_uuid(), owner.user_id, ca.org_id, NULL,
               'analyses', 'cloud', 1, 'cloud_scan', s.id,
               COALESCE(s.created_at, NOW())
        FROM cloud_scan s
        JOIN cloud_account ca ON ca.id = s.cloud_account_id
        JOIN owner ON owner.org_id = ca.org_id
        WHERE s.status <> 'no_targets'
        """
    )

    # Fix generations have no per-event timestamps — the lifetime counter is
    # just an integer. One carry-over record per subscription, dated at
    # period_start and sized to exactly what the old formula reported for the
    # current period, so nobody's usage bar moves on deploy day.
    op.execute(
        f"""
        WITH owner AS ({_BILLING_OWNER}),
        lifetime AS (
            SELECT owner.user_id,
                   -- Any one of the owner's orgs will do: the record is a
                   -- per-user carry-over, and org_id is NOT NULL. Postgres has
                   -- no MIN() for uuid, hence array_agg.
                   (ARRAY_AGG(r.org_id ORDER BY r.org_id))[1] AS org_id,
                   COALESCE(SUM(wf.fix_generation_count), 0) AS total
            FROM workflow_file wf
            JOIN repository r ON r.id = wf.repo_id
            JOIN owner ON owner.org_id = r.org_id
            GROUP BY owner.user_id
        )
        INSERT INTO billing_usage_record
            (id, user_id, org_id, repo_id, meter, engine, quantity,
             source_type, source_id, occurred_at)
        SELECT gen_random_uuid(), bs.user_id, lifetime.org_id, NULL,
               'fixes', 'carryover',
               GREATEST(lifetime.total - bs.fixes_used_baseline, 0),
               'migration_0050', NULL,
               COALESCE(bs.period_start, NOW())
        FROM billing_subscription bs
        JOIN lifetime ON lifetime.user_id = bs.user_id
        WHERE GREATEST(lifetime.total - bs.fixes_used_baseline, 0) > 0
        """
    )


def downgrade() -> None:
    op.add_column(
        "billing_subscription",
        sa.Column("analyses_used", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "billing_subscription",
        sa.Column("fixes_used", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "billing_subscription",
        sa.Column(
            "fixes_used_baseline", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    # Recompute the baseline the way the old code would have snapshotted it:
    # the lifetime sum minus whatever the ledger says was spent this period.
    # The ledger's per-event history has nowhere to live in the old schema and
    # is lost here; that is the one-way part of this migration.
    op.execute(
        f"""
        WITH owner AS ({_BILLING_OWNER}),
        lifetime AS (
            SELECT owner.user_id,
                   COALESCE(SUM(wf.fix_generation_count), 0) AS total
            FROM workflow_file wf
            JOIN repository r ON r.id = wf.repo_id
            JOIN owner ON owner.org_id = r.org_id
            GROUP BY owner.user_id
        ),
        spent AS (
            SELECT ur.user_id, COALESCE(SUM(ur.quantity), 0) AS used
            FROM billing_usage_record ur
            JOIN billing_subscription bs ON bs.user_id = ur.user_id
            WHERE ur.meter = 'fixes'
              AND (bs.period_start IS NULL OR ur.occurred_at >= bs.period_start)
            GROUP BY ur.user_id
        )
        UPDATE billing_subscription bs
        SET fixes_used_baseline = GREATEST(
                COALESCE(lifetime.total, 0) - COALESCE(spent.used, 0), 0
            )
        FROM lifetime
        LEFT JOIN spent ON spent.user_id = lifetime.user_id
        WHERE lifetime.user_id = bs.user_id
        """
    )

    op.drop_index(
        "ix_billing_webhook_event_stripe_event_id", table_name="billing_webhook_event"
    )
    op.drop_table("billing_webhook_event")
    op.drop_index(
        "ix_billing_oss_application_user_id", table_name="billing_oss_application"
    )
    op.drop_table("billing_oss_application")
    op.drop_index("ix_billing_invoice_stripe_invoice_id", table_name="billing_invoice")
    op.drop_table("billing_invoice")
    op.drop_index(
        "ix_billing_usage_record_user_meter_time", table_name="billing_usage_record"
    )
    op.drop_index("ix_billing_usage_record_user_id", table_name="billing_usage_record")
    op.drop_table("billing_usage_record")

    for column in (
        "canceled_at",
        "cancel_at_period_end",
        "trial_end",
        "quota_warning_percent",
        "dunning_stage",
        "grace_expires_at",
        "past_due_since",
        "status",
    ):
        op.drop_column("billing_subscription", column)
