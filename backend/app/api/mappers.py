from app.models import (
    Analysis,
    AnalysisPublic,
    Issue,
    IssuePublic,
    Repository,
    RepositoryPublic,
)


def to_analysis_public(analysis: Analysis) -> AnalysisPublic:
    return AnalysisPublic(
        id=analysis.id,
        repo_id=analysis.repo_id,
        workflow_file_id=analysis.workflow_file_id,
        workflow_file_path=(
            analysis.workflow_file.path if analysis.workflow_file else None
        ),
        repo_full_name=(analysis.repository.full_name if analysis.repository else None),
        content_hash=analysis.content_hash,
        status=analysis.status,
        score=analysis.score,
        grade=analysis.grade,
        triggered_by=analysis.triggered_by,
        branch=analysis.branch,
        commit_sha=analysis.commit_sha,
        created_at=analysis.created_at,
        completed_at=analysis.completed_at,
    )


def to_issue_public(issue: Issue) -> IssuePublic:
    fix = issue.fix
    analysis = issue.analysis
    workflow_file_path = (
        analysis.workflow_file.path if analysis and analysis.workflow_file else None
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
        created_at=issue.created_at,
        resolved_at=issue.resolved_at,
        fix_id=fix.id if fix else None,
        fix_status=fix.status if fix else None,
        workflow_file_path=workflow_file_path,
    )


def to_repo_public(
    repo: Repository, avg_score: float | None, grade: str | None
) -> RepositoryPublic:
    return RepositoryPublic(
        id=repo.id,
        full_name=repo.full_name,
        enabled=repo.enabled,
        is_accessible=repo.is_accessible,
        is_external=repo.is_external,
        default_branch=repo.default_branch,
        auto_fix_enabled=repo.auto_fix_enabled,
        created_at=repo.created_at,
        avg_score=avg_score,
        grade=grade,
    )
