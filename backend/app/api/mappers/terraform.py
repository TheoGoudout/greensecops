from app.models import (
    ScanStatus,
    TerraformFinding,
    TerraformFindingPublic,
    TerraformFix,
    TerraformFixPublic,
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
    fix = finding.fix
    return TerraformFindingPublic(
        id=finding.id,
        scan_id=finding.scan_id,
        terraform_root_id=finding.terraform_root_id,
        rule_id=finding.rule_id,
        rule_slug=finding.rule.slug if finding.rule else "",
        resource_address=finding.resource_address,
        file_path=finding.file_path,
        line_start=finding.line_start,
        line_end=finding.line_end,
        module_path=finding.module_path,
        terraform_address=finding.terraform_address,
        severity=finding.severity,
        category=finding.category,
        message=finding.message,
        context=finding.context,
        status=finding.status,
        fix_id=fix.id if fix else None,
        fix_status=fix.status if fix else None,
        created_at=finding.created_at,
        resolved_at=finding.resolved_at,
        resolution_reason=finding.resolution_reason,
    )


def to_terraform_fix_public(fix: TerraformFix) -> TerraformFixPublic:
    pr = fix.pull_request
    return TerraformFixPublic(
        id=fix.id,
        terraform_root_id=fix.terraform_root_id,
        file_path=fix.file_path,
        pr_id=fix.pr_id,
        llm_provider=fix.llm_provider,
        llm_model=fix.llm_model,
        status=fix.status,
        full_content=fix.full_content,
        error_message=fix.error_message,
        pr_url=pr.pr_url if pr else None,
        pr_branch=pr.pr_branch if pr else None,
        pr_state=pr.pr_state if pr else None,
        created_at=fix.created_at,
        delivered_at=fix.delivered_at,
    )
