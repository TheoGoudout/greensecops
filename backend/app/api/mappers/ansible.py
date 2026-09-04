from app.models import (
    AnsibleFinding,
    AnsibleFindingPublic,
    AnsibleFix,
    AnsibleFixPublic,
    AnsibleProject,
    AnsibleProjectPublic,
    AnsibleScan,
    AnsibleScanPublic,
)
from app.models.enums import TargetActivity
from app.services.badge_signing import sign_badge

from .base import latest_completed_scan, latest_scan_status, to_public


def to_ansible_project_public(
    project: AnsibleProject,
    activity: TargetActivity = TargetActivity.idle,
) -> AnsibleProjectPublic:
    # Passed in, not read off the row — see ``to_terraform_root_public``.
    latest = latest_completed_scan(project)
    badge_sig: str | None = None
    if project.repository and project.repository.is_private:
        badge_sig = sign_badge(str(project.id))
    return to_public(
        project,
        AnsibleProjectPublic,
        repo_full_name=project.repository.full_name if project.repository else None,
        latest_score=latest.score if latest else None,
        latest_grade=latest.grade if latest else None,
        latest_scan_status=latest_scan_status(project),
        activity=activity,
        badge_sig=badge_sig,
    )


def to_ansible_scan_public(scan: AnsibleScan) -> AnsibleScanPublic:
    return to_public(scan, AnsibleScanPublic)


def to_ansible_finding_public(finding: AnsibleFinding) -> AnsibleFindingPublic:
    fix = finding.fix
    return to_public(
        finding,
        AnsibleFindingPublic,
        rule_slug=finding.rule.slug if finding.rule else "",
        fix_id=fix.id if fix else None,
        fix_status=fix.status if fix else None,
    )


def to_ansible_fix_public(fix: AnsibleFix) -> AnsibleFixPublic:
    pr = fix.pull_request
    return to_public(
        fix,
        AnsibleFixPublic,
        pr_url=pr.pr_url if pr else None,
        pr_branch=pr.pr_branch if pr else None,
        pr_state=pr.pr_state if pr else None,
    )
