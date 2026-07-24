from app.models import (
    CloudAccount,
    CloudAccountPublic,
    CloudFinding,
    CloudFindingPublic,
    CloudScan,
    CloudScanPublic,
    ScanStatus,
)


def latest_completed_cloud_scan(account: CloudAccount) -> CloudScan | None:
    """The account's most recently completed scan, if any."""
    return max(
        (s for s in account.scans if s.status == ScanStatus.completed),
        key=lambda s: s.created_at or 0,
        default=None,
    )


def to_cloud_account_public(account: CloudAccount) -> CloudAccountPublic:
    latest_completed = latest_completed_cloud_scan(account)
    return CloudAccountPublic(
        id=account.id,
        org_id=account.org_id,
        provider=account.provider,
        display_name=account.display_name,
        role_arn=account.role_arn,
        external_id=account.external_id,
        regions=[r for r in account.regions.split(",") if r],
        status=account.status,
        last_synced_at=account.last_synced_at,
        latest_score=latest_completed.score if latest_completed else None,
        latest_grade=latest_completed.grade if latest_completed else None,
        created_at=account.created_at,
    )


def to_cloud_scan_public(scan: CloudScan) -> CloudScanPublic:
    return CloudScanPublic(
        id=scan.id,
        cloud_account_id=scan.cloud_account_id,
        status=scan.status,
        triggered_by=scan.triggered_by,
        region=scan.region,
        resource_count=scan.resource_count,
        score=scan.score,
        grade=scan.grade,
        error_message=scan.error_message,
        created_at=scan.created_at,
        completed_at=scan.completed_at,
    )


def to_cloud_finding_public(finding: CloudFinding) -> CloudFindingPublic:
    return CloudFindingPublic(
        id=finding.id,
        scan_id=finding.scan_id,
        cloud_account_id=finding.cloud_account_id,
        rule_id=finding.rule_id,
        rule_slug=finding.rule.slug if finding.rule else "",
        resource_type=finding.resource_type,
        resource_id=finding.resource_id,
        region=finding.region,
        severity=finding.severity,
        category=finding.category,
        message=finding.message,
        context=finding.context,
        status=finding.status,
        created_at=finding.created_at,
        resolved_at=finding.resolved_at,
        resolution_reason=finding.resolution_reason,
    )
