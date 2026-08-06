from app.models import (
    CloudAccount,
    CloudAccountPublic,
    CloudFinding,
    CloudFindingPublic,
    CloudScan,
    CloudScanPublic,
)

from .base import latest_completed_scan, to_public


def to_cloud_account_public(account: CloudAccount) -> CloudAccountPublic:
    latest = latest_completed_scan(account)
    return to_public(
        account,
        CloudAccountPublic,
        # Stored comma-separated; the API exposes a real list.
        regions=[r for r in account.regions.split(",") if r],
        latest_score=latest.score if latest else None,
        latest_grade=latest.grade if latest else None,
    )


def to_cloud_scan_public(scan: CloudScan) -> CloudScanPublic:
    return to_public(scan, CloudScanPublic)


def to_cloud_finding_public(finding: CloudFinding) -> CloudFindingPublic:
    return to_public(
        finding,
        CloudFindingPublic,
        rule_slug=finding.rule.slug if finding.rule else "",
    )
