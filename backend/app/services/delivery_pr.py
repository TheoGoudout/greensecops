"""Shared helpers for delivering fixes as GitHub PRs.

The single-fix route, the deliver-all route and the auto-delivery worker all
mint the same deterministic fix-branch names and render the same PR body from
the set of fixes on the PR. Keeping the branch constructors next to the parser
regex guarantees the two can't drift.
"""

import re
import uuid

from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import Fix, PullRequest, WorkflowFile
from app.services.pr_body import IssueInfo, build_pr_body
from app.services.state_machines import DELIVERED_FIX_STATUSES

# Matches the single-file fix branch ``greensecops/fixes-wf-<workflow_file_id[:8]>``
# minted by wf_fix_branch(). The 8-hex group reverses to the workflow file whose
# id starts with it.
WF_FIX_BRANCH_RE = re.compile(r"greensecops/fixes-wf-([0-9a-f]{8})$")


def wf_fix_branch(workflow_file_id: uuid.UUID) -> str:
    """Deterministic branch for a single workflow file's fix PR."""
    return f"greensecops/fixes-wf-{str(workflow_file_id)[:8]}"


def repo_fix_branch(repo_id: uuid.UUID) -> str:
    """Deterministic branch for a repo-wide batch fix PR."""
    return f"greensecops/fixes-{str(repo_id)[:8]}"


def issues_info_for_fixes(fixes: list[Fix]) -> list[IssueInfo]:
    """Build PR-body issue summaries from the issues each fix actually resolved.

    An issue the LLM flagged as ``needs_manual_work`` was never fixed in this
    diff, so it's excluded here rather than listed as "fixed".
    """
    return [
        IssueInfo(
            rule_slug=issue.rule.slug if issue.rule else "fix",
            rule_title=issue.rule.title if issue.rule else "Fix",
            category=issue.category.value if issue.category else "unknown",
            severity=issue.severity.value if issue.severity else "unknown",
            message=issue.message or "",
            workflow_path=fix.workflow_file.path if fix.workflow_file else "unknown",
            line_start=issue.line_start,
        )
        for fix in fixes
        for issue in fix.issues
        if not issue.needs_manual_work
    ]


def build_delivery_pr_body(
    session: Session,
    repo_id: uuid.UUID,
    fixes: list[Fix],
    existing_pr: PullRequest | None,
) -> str:
    """Render the PR body for delivering ``fixes`` onto ``existing_pr``.

    The body must reflect every fix ever delivered onto the PR, not just this
    batch — ``existing_pr`` may be shared with other workflows' fixes (e.g. a
    repo-wide batch PR), and overwriting the body with only the current fixes
    would wipe the other rows out of the description.
    """
    body_fixes = list(fixes)
    if existing_pr:
        current_ids = {f.id for f in fixes}
        prior_fixes = session.exec(
            select(Fix)
            .join(WorkflowFile, Fix.workflow_file_id == WorkflowFile.id)  # type: ignore[arg-type]
            .where(
                WorkflowFile.repo_id == repo_id,
                Fix.pr_id == existing_pr.id,
                col(Fix.status).in_(DELIVERED_FIX_STATUSES),
            )
        ).all()
        body_fixes.extend(f for f in prior_fixes if f.id not in current_ids)

    return build_pr_body(
        issues=issues_info_for_fixes(body_fixes),
        fix_ids=[str(f.id) for f in body_fixes],
        wiki_base_url=settings.WIKI_BASE_URL,
        frontend_host=settings.FRONTEND_HOST,
        bot_handle=settings.GITHUB_BOT_HANDLE,
        app_name=settings.PROJECT_NAME,
        app_url=settings.APP_URL,
    )
