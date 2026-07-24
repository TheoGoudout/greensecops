from app.models import (
    ScanStatus,
    TerraformFinding,
    TerraformFindingPublic,
    TerraformRoot,
    TerraformRootPublic,
    TerraformScan,
    TerraformScanPublic,
)


def latest_completed_terraform_scan(root: TerraformRoot) -> TerraformScan | None:
    """The root's most recently completed scan, if any.

    Shared by the mapper (below) and the Terraform badge route — both need
    "what grade is this root at right now", and a root's grade IS its latest
    completed scan's grade, there's no separate aggregation to keep in sync.
    """
    return max(
        (s for s in root.scans if s.status == ScanStatus.completed),
        key=lambda s: s.created_at or 0,
        default=None,
    )


def to_terraform_root_public(root: TerraformRoot) -> TerraformRootPublic:
    latest_completed = latest_completed_terraform_scan(root)
    badge_sig: str | None = None
    if root.repository and root.repository.is_private:
        from app.services.badge_signing import sign_terraform_root_badge

        badge_sig = sign_terraform_root_badge(str(root.id))
    return TerraformRootPublic(
        id=root.id,
        repo_id=root.repo_id,
        repo_full_name=root.repository.full_name if root.repository else None,
        root_path=root.root_path,
        enabled=root.enabled,
        last_scanned_at=root.last_scanned_at,
        last_scanned_head_sha=root.last_scanned_head_sha,
        latest_score=latest_completed.score if latest_completed else None,
        latest_grade=latest_completed.grade if latest_completed else None,
        badge_sig=badge_sig,
    )


def to_terraform_scan_public(scan: TerraformScan) -> TerraformScanPublic:
    return TerraformScanPublic(
        id=scan.id,
        terraform_root_id=scan.terraform_root_id,
        status=scan.status,
        triggered_by=scan.triggered_by,
        branch=scan.branch,
        commit_sha=scan.commit_sha,
        score=scan.score,
        grade=scan.grade,
        error_message=scan.error_message,
        created_at=scan.created_at,
        completed_at=scan.completed_at,
    )


def to_terraform_finding_public(finding: TerraformFinding) -> TerraformFindingPublic:
    return TerraformFindingPublic(
        id=finding.id,
        scan_id=finding.scan_id,
        terraform_root_id=finding.terraform_root_id,
        rule_id=finding.rule_id,
        rule_slug=finding.rule.slug if finding.rule else "",
        resource_address=finding.resource_address,
        file_path=finding.file_path,
        severity=finding.severity,
        category=finding.category,
        message=finding.message,
        context=finding.context,
        status=finding.status,
        created_at=finding.created_at,
        resolved_at=finding.resolved_at,
        resolution_reason=finding.resolution_reason,
    )
