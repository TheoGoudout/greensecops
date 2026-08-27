from app.models import (
    TerraformFinding,
    TerraformFindingPublic,
    TerraformFix,
    TerraformFixPublic,
    TerraformRoot,
    TerraformRootPublic,
    TerraformScan,
    TerraformScanPublic,
)
from app.services.badge_signing import sign_badge

from .base import latest_completed_scan, latest_scan_status, to_public


def to_terraform_root_public(root: TerraformRoot) -> TerraformRootPublic:
    latest = latest_completed_scan(root)
    badge_sig: str | None = None
    if root.repository and root.repository.is_private:
        # Function-local import: badge_signing pulls in settings, and with it a
        # chunk of the app at module scope.

        badge_sig = sign_badge(str(root.id))
    return to_public(
        root,
        TerraformRootPublic,
        repo_full_name=root.repository.full_name if root.repository else None,
        latest_score=latest.score if latest else None,
        latest_grade=latest.grade if latest else None,
        latest_scan_status=latest_scan_status(root),
        badge_sig=badge_sig,
    )


def to_terraform_scan_public(scan: TerraformScan) -> TerraformScanPublic:
    return to_public(scan, TerraformScanPublic)


def to_terraform_finding_public(finding: TerraformFinding) -> TerraformFindingPublic:
    fix = finding.fix
    return to_public(
        finding,
        TerraformFindingPublic,
        rule_slug=finding.rule.slug if finding.rule else "",
        fix_id=fix.id if fix else None,
        fix_status=fix.status if fix else None,
    )


def to_terraform_fix_public(fix: TerraformFix) -> TerraformFixPublic:
    pr = fix.pull_request
    return to_public(
        fix,
        TerraformFixPublic,
        pr_url=pr.pr_url if pr else None,
        pr_branch=pr.pr_branch if pr else None,
        pr_state=pr.pr_state if pr else None,
    )
