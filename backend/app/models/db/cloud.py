import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from ..enums import CloudAccountStatus, CloudProvider
from .base import get_datetime_utc
from .mixins import FindingMixin, ScanMixin

if TYPE_CHECKING:
    from .organization import Organization
    from .rule import Rule


class CloudAccount(SQLModel, table=True):
    """An org-level connection to a cloud provider account (AWS only for now).

    Not tied to a single repository: one AWS account's posture is scanned
    independently of any repo's code — which is why this is not a
    ``ScanTargetMixin`` table. Cross-account sts:AssumeRole + ExternalId only
    — no static access keys are ever accepted or stored, so this table
    deliberately has no credential/secret column.
    """

    __tablename__ = "cloud_account"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    org_id: uuid.UUID = Field(
        foreign_key="organization.id", nullable=False, ondelete="CASCADE"
    )
    provider: CloudProvider = Field(default=CloudProvider.aws)
    display_name: str = Field(max_length=255)
    role_arn: str | None = Field(default=None, max_length=512)
    # Generated per account and shown to the user for their role's trust
    # policy condition; not a secret by itself (the trust relationship scoped
    # to our AWS account + this value is what grants access), but unique so
    # one can't be replayed against a different account's role.
    external_id: str = Field(max_length=64, unique=True)
    # Comma-separated region codes; simple string is enough for the curated
    # MVP resource set, revisit if per-region config grows more structured.
    regions: str = Field(default="", max_length=1024)
    status: CloudAccountStatus = Field(
        default=CloudAccountStatus.pending_verification,
        sa_column_kwargs={
            "server_default": CloudAccountStatus.pending_verification.value
        },
    )
    last_synced_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    organization: Optional["Organization"] = Relationship(
        back_populates="cloud_accounts"
    )
    scans: list["CloudScan"] = Relationship(
        back_populates="cloud_account", cascade_delete=True
    )


class CloudScan(ScanMixin, table=True):
    """A sweep of one account's live resources.

    Plain ``ScanMixin``, not ``RepoScanMixin``: there is no branch or commit
    behind a cloud scan, only a region and a moment in time.
    """

    __tablename__ = "cloud_scan"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    cloud_account_id: uuid.UUID = Field(
        foreign_key="cloud_account.id", nullable=False, ondelete="CASCADE"
    )
    region: str | None = Field(default=None, max_length=32)
    resource_count: int = Field(default=0)
    cloud_account: CloudAccount | None = Relationship(back_populates="scans")
    findings: list["CloudFinding"] = Relationship(
        back_populates="scan", cascade_delete=True
    )


class CloudFinding(FindingMixin, table=True):
    __tablename__ = "cloud_finding"
    __table_args__ = (
        UniqueConstraint(
            "cloud_account_id",
            "fingerprint",
            name="uq_cloud_finding_account_fingerprint",
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    scan_id: uuid.UUID = Field(
        foreign_key="cloud_scan.id", nullable=False, ondelete="CASCADE"
    )
    # Denormalized off the scan for the same reason as TerraformFinding: the
    # fingerprint's history scope is the account across scans, not one scan.
    cloud_account_id: uuid.UUID = Field(
        foreign_key="cloud_account.id", nullable=False, ondelete="CASCADE"
    )
    resource_type: str = Field(max_length=255)
    resource_id: str = Field(max_length=1024)
    region: str | None = Field(default=None, max_length=32)
    scan: CloudScan | None = Relationship(back_populates="findings")
    # One-directional (no back_populates on Rule), mirrors TerraformFinding.rule.
    rule: Optional["Rule"] = Relationship()
