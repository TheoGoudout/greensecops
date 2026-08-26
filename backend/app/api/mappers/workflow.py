from app.models import (
    WorkflowFinding,
    WorkflowFindingPublic,
    WorkflowScan,
    WorkflowScanPublic,
)


def to_workflow_scan_public(scan: WorkflowScan) -> WorkflowScanPublic:
    return WorkflowScanPublic(
        id=scan.id,
        repo_id=scan.repo_id,
        workflow_file_id=scan.workflow_file_id,
        file_path=(scan.workflow_file.path if scan.workflow_file else None),
        repo_full_name=(scan.repository.full_name if scan.repository else None),
        content_hash=scan.content_hash,
        status=scan.status,
        score=scan.score,
        grade=scan.grade,
        error_message=scan.error_message,
        triggered_by=scan.triggered_by,
        branch=scan.branch,
        commit_sha=scan.commit_sha,
        created_at=scan.created_at,
        completed_at=scan.completed_at,
    )


def to_workflow_finding_public(finding: WorkflowFinding) -> WorkflowFindingPublic:
    fix = finding.fix
    scan = finding.scan
    file_path = scan.workflow_file.path if scan and scan.workflow_file else None
    return WorkflowFindingPublic(
        id=finding.id,
        # ``analysis_id`` is the column the table still carries; every engine's
        # public finding calls it ``scan_id``.
        scan_id=finding.analysis_id,
        rule_id=finding.rule_id,
        rule_slug=finding.rule.slug if finding.rule else "",
        severity=finding.severity,
        category=finding.category,
        line_start=finding.line_start,
        line_end=finding.line_end,
        message=finding.message,
        context=finding.context,
        status=finding.status,
        created_at=finding.created_at,
        resolved_at=finding.resolved_at,
        resolution_reason=finding.resolution_reason,
        needs_manual_work=finding.needs_manual_work,
        manual_work_note=finding.manual_work_note,
        fix_id=fix.id if fix else None,
        fix_status=fix.status if fix else None,
        file_path=file_path,
    )
