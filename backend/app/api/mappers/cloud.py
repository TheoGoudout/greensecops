from app.models import (
    CloudAccount,
    CloudAccountPublic,
    CloudFinding,
    CloudFindingPublic,
    CloudScan,
    CloudScanPublic,
)
from app.models.enums import TargetActivity
from app.services.badge_signing import sign_badge

from .base import latest_completed_scan, latest_scan_status, to_public


def to_cloud_account_public(
    account: CloudAccount,
    activity: TargetActivity = TargetActivity.idle,
) -> CloudAccountPublic:
    # Passed in, not read off the row — see ``to_terraform_root_public``. Cloud
    # has no fixes, so the answer is its latest scan alone, but it is still the
    # caller's batched query rather than a per-row one.
    latest = latest_completed_scan(account)
    return to_public(
        account,
        CloudAccountPublic,
        # Stored comma-separated; the API exposes a real list.
        regions=[r for r in account.regions.split(",") if r],
        latest_score=latest.score if latest else None,
        latest_grade=latest.grade if latest else None,
        latest_scan_status=latest_scan_status(account),
        activity=activity,
        # Always signed, unlike the repo-backed engines' conditional-on-private
        # badge_sig — a cloud account has no public counterpart to fall back to.
        badge_sig=sign_badge(str(account.id)),
    )


def to_cloud_scan_public(scan: CloudScan) -> CloudScanPublic:
    return to_public(scan, CloudScanPublic)


def to_cloud_finding_public(finding: CloudFinding) -> CloudFindingPublic:
    return to_public(
        finding,
        CloudFindingPublic,
        rule_slug=finding.rule.slug if finding.rule else "",
    )
