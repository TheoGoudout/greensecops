"""ORM → public-schema mappers for the Docker engine.

Mirrors ``mappers/terraform.py``. The mappers exist so route handlers never
traverse relationships inline — a finding's rule slug and a target's grade are
derived in one place, and the badge route reuses
``latest_completed_docker_scan`` so a target's grade has a single definition.
"""

from app.models import (
    DockerFinding,
    DockerFindingPublic,
    DockerFix,
    DockerFixPublic,
    DockerScan,
    DockerScanPublic,
    DockerTarget,
    DockerTargetPublic,
    ScanStatus,
)


def latest_completed_docker_scan(target: DockerTarget) -> DockerScan | None:
    """The target's most recent successfully completed scan, if any.

    A failed or in-flight scan must not define the grade: a target whose latest
    scan errored still has the grade its last good scan produced.
    """
    return max(
        (s for s in target.scans if s.status == ScanStatus.completed),
        key=lambda s: s.created_at or 0,
        default=None,
    )


def to_docker_target_public(target: DockerTarget) -> DockerTargetPublic:
    latest_completed = latest_completed_docker_scan(target)
    badge_sig: str | None = None
    if target.repository and target.repository.is_private:
        # Function-local import: badge_signing imports settings, which pulls in
        # a chunk of the app at module scope — the same dodge
        # mappers/terraform.py uses to avoid a cycle.
        from app.services.badge_signing import sign_docker_target_badge

        badge_sig = sign_docker_target_badge(str(target.id))
    return DockerTargetPublic(
        id=target.id,
        repo_id=target.repo_id,
        repo_full_name=target.repository.full_name if target.repository else None,
        root_path=target.root_path,
        enabled=target.enabled,
        last_scanned_at=target.last_scanned_at,
        last_scanned_head_sha=target.last_scanned_head_sha,
        latest_score=latest_completed.score if latest_completed else None,
        latest_grade=latest_completed.grade if latest_completed else None,
        badge_sig=badge_sig,
    )


def to_docker_scan_public(scan: DockerScan) -> DockerScanPublic:
    return DockerScanPublic(
        id=scan.id,
        docker_target_id=scan.docker_target_id,
        status=scan.status,
        triggered_by=scan.triggered_by,
        branch=scan.branch,
        commit_sha=scan.commit_sha,
        score=scan.score,
        grade=scan.grade,
        file_count=scan.file_count,
        error_message=scan.error_message,
        created_at=scan.created_at,
        completed_at=scan.completed_at,
    )


def to_docker_finding_public(finding: DockerFinding) -> DockerFindingPublic:
    fix = finding.fix
    return DockerFindingPublic(
        id=finding.id,
        scan_id=finding.scan_id,
        docker_target_id=finding.docker_target_id,
        rule_id=finding.rule_id,
        rule_slug=finding.rule.slug if finding.rule else "",
        file_path=finding.file_path,
        service_name=finding.service_name,
        stage_name=finding.stage_name,
        line_start=finding.line_start,
        line_end=finding.line_end,
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


def to_docker_fix_public(fix: DockerFix) -> DockerFixPublic:
    pr = fix.pull_request
    return DockerFixPublic(
        id=fix.id,
        docker_target_id=fix.docker_target_id,
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
