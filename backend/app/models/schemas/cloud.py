"""The cloud-posture engine: connected accounts, scans and findings."""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from ..enums import (
    CloudAccountStatus,
    CloudProvider,
    ScanStatus,
    TargetActivity,
)
from .base import (
    FindingPublicBase,
    ScanPublicBase,
)


class CloudAccountCreate(SQLModel):
    org_id: uuid.UUID
    display_name: str = Field(max_length=255)
    role_arn: str = Field(max_length=512)
    regions: list[str] = Field(default_factory=list)


class CloudAccountPublic(SQLModel):
    id: uuid.UUID
    org_id: uuid.UUID
    provider: CloudProvider
    display_name: str
    role_arn: str | None = None
    external_id: str
    regions: list[str] = []
    status: CloudAccountStatus
    last_synced_at: datetime | None = None
    # Populated from the account's latest scan, mirroring TerraformRootPublic.
    latest_score: float | None = None
    latest_grade: str | None = None
    latest_scan_status: ScanStatus | None = None
    # Same field, same meaning and same source as ``ScanTargetPublicBase``'s,
    # spelled out because a cloud account is not a repo-backed scan target and
    # so does not inherit that base. Cloud has no fixes, so the only activity it
    # ever reports is ``scanning``.
    activity: TargetActivity = TargetActivity.idle
    # Unlike a Terraform root or Docker target, a cloud account has no public
    # repo to inherit visibility from — an AWS account's posture is sensitive
    # regardless, so this is always set, never conditional on a privacy flag.
    badge_sig: str | None = None
    created_at: datetime | None = None


class CloudScanPublic(ScanPublicBase):
    cloud_account_id: uuid.UUID
    region: str | None = None
    resource_count: int = 0


class CloudFindingPublic(FindingPublicBase):
    cloud_account_id: uuid.UUID
    resource_type: str
    resource_id: str
    region: str | None = None


# The cross-engine dashboard overview. Everything below is an *aggregate* view
# of the shapes the bases above describe — no row of any of these is persisted.
# It lives here, after the last per-engine block, because it reuses
# ``FindingCategoryStat`` from the CI block and the engine enums from all four.
