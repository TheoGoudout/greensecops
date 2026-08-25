from app.models import AnalysisPublic, IssuePublic, WorkflowFinding, WorkflowScan


def to_analysis_public(scan: WorkflowScan) -> AnalysisPublic:
    return AnalysisPublic(
        id=scan.id,
        repo_id=scan.repo_id,
        workflow_file_id=scan.workflow_file_id,
        workflow_file_path=(scan.workflow_file.path if scan.workflow_file else None),
        repo_full_name=(scan.repository.full_name if scan.repository else None),
        content_hash=scan.content_hash,
        status=scan.status,
        score=scan.score,
        grade=scan.grade,
        triggered_by=scan.triggered_by,
        branch=scan.branch,
        commit_sha=scan.commit_sha,
        created_at=scan.created_at,
        completed_at=scan.completed_at,
    )


def to_issue_public(issue: WorkflowFinding) -> IssuePublic:
    fix = issue.fix
    scan = issue.scan
    workflow_file_path = (
        scan.workflow_file.path if scan and scan.workflow_file else None
    )
    return IssuePublic(
        id=issue.id,
        analysis_id=issue.analysis_id,
        rule_id=issue.rule_id,
        rule_slug=issue.rule.slug if issue.rule else "",
        severity=issue.severity,
        category=issue.category,
        line_start=issue.line_start,
        line_end=issue.line_end,
        message=issue.message,
        context=issue.context,
        status=issue.status,
        created_at=issue.created_at,
        resolved_at=issue.resolved_at,
        resolution_reason=issue.resolution_reason,
        needs_manual_work=issue.needs_manual_work,
        manual_work_note=issue.manual_work_note,
        fix_id=fix.id if fix else None,
        fix_status=fix.status if fix else None,
        workflow_file_path=workflow_file_path,
    )
