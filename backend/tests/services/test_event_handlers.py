"""Unit tests for the source-agnostic GitHub event handlers.

These handlers back both the webhook route and the external-repo poller, so the
webhook end-to-end coverage in ``tests/api/routes/test_webhooks.py`` exercises
them from the webhook side. Here we call them directly to lock in the behaviour
the poller depends on — in particular that a merged PR **lands** its fixes and
resolves their issues (the reconciliation the old polling path was missing).
"""

import uuid

from sqlmodel import Session, select

from app.models import (
    Category,
    CIStatus,
    FindingResolutionReason,
    FixStatus,
    LLMProvider,
    Organization,
    PullRequest,
    PullRequestState,
    Repository,
    ReviewDecision,
    Rule,
    ScanStatus,
    ScanTrigger,
    Severity,
    UserTier,
    WorkflowFile,
    WorkflowFinding,
    WorkflowFix,
    WorkflowScan,
)
from app.services.github import event_handlers as eh


def _build_pr_with_delivered_fix(
    db: Session,
    *,
    is_external: bool = True,
) -> tuple[Repository, PullRequest, WorkflowFix, WorkflowFinding]:
    org = Organization(name=f"eh-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(org)
    db.commit()
    db.refresh(org)

    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"eh/repo-{uuid.uuid4().hex[:8]}",
        installation_id=None if is_external else 55501,
        is_external=is_external,
        default_branch="main",
        enabled=True,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/ci.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\n",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)

    analysis = WorkflowScan(
        repo_id=repo.id,
        workflow_file_id=wf.id,
        content_hash=wf.content_hash,
        status=ScanStatus.completed,
        triggered_by=ScanTrigger.manual,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    rule = Rule(
        slug=f"eh_rule_{uuid.uuid4().hex[:8]}",
        category=Category.security,
        severity=Severity.high,
        title="t",
        description="d",
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    pr = PullRequest(
        repo_id=repo.id,
        pr_branch=f"greensecops/eh-{uuid.uuid4().hex[:8]}",
        pr_url=f"https://github.com/{repo.full_name}/pull/7",
        pr_state=PullRequestState.open,
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    fix = WorkflowFix(
        workflow_file_id=wf.id,
        pr_id=pr.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.delivered,
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)

    issue = WorkflowFinding(
        analysis_id=analysis.id,
        workflow_file_id=wf.id,
        rule_id=rule.id,
        fingerprint=uuid.uuid4().hex[:16],
        severity=Severity.high,
        category=Category.security,
        message="m",
        fix_id=fix.id,
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)

    return repo, pr, fix, issue


def test_merge_lands_fixes_and_resolves_issues(db: Session) -> None:
    _, pr, fix, issue = _build_pr_with_delivered_fix(db)

    eh.handle_pull_request_lifecycle(db, pr, "merge")

    db.refresh(pr)
    db.refresh(fix)
    db.refresh(issue)
    assert pr.pr_state == PullRequestState.merged
    assert fix.status == FixStatus.landed
    assert issue.resolved_at is not None
    assert issue.resolution_reason == FindingResolutionReason.merged


def test_close_supersedes_delivered_fix(db: Session) -> None:
    _, pr, fix, _ = _build_pr_with_delivered_fix(db)

    eh.handle_pull_request_lifecycle(db, pr, "close")

    db.refresh(pr)
    db.refresh(fix)
    assert pr.pr_state == PullRequestState.closed
    assert fix.status == FixStatus.superseded_by_closed_pr


def test_reopen_restores_superseded_fix(db: Session) -> None:
    _, pr, fix, _ = _build_pr_with_delivered_fix(db)
    eh.handle_pull_request_lifecycle(db, pr, "close")
    db.refresh(pr)
    db.refresh(fix)
    assert fix.status == FixStatus.superseded_by_closed_pr

    eh.handle_pull_request_lifecycle(db, pr, "reopen")
    db.refresh(pr)
    db.refresh(fix)
    assert pr.pr_state == PullRequestState.open
    assert fix.status == FixStatus.ready


def test_ci_status_recorded(db: Session) -> None:
    _, pr, _, _ = _build_pr_with_delivered_fix(db)
    eh.handle_ci_status(db, pr, CIStatus.failure)
    db.refresh(pr)
    assert pr.ci_status == CIStatus.failure


def test_review_decision_recorded(db: Session) -> None:
    _, pr, _, _ = _build_pr_with_delivered_fix(db)
    eh.handle_review_decision(db, pr, ReviewDecision.changes_requested)
    db.refresh(pr)
    assert pr.review_decision == ReviewDecision.changes_requested


def test_sync_bumps_updated_at(db: Session) -> None:
    _, pr, _, _ = _build_pr_with_delivered_fix(db)
    assert pr.updated_at is None
    eh.handle_pull_request_sync(db, pr, mergeable_state="clean")
    db.refresh(pr)
    assert pr.updated_at is not None
    assert pr.mergeable_state == "clean"


def test_draft_toggle_moves_state(db: Session) -> None:
    _, pr, _, _ = _build_pr_with_delivered_fix(db)
    eh.handle_pull_request_draft_toggle(db, pr, "convert_to_draft")
    db.refresh(pr)
    assert pr.pr_state == PullRequestState.draft
    eh.handle_pull_request_draft_toggle(db, pr, "mark_ready_for_review")
    db.refresh(pr)
    assert pr.pr_state == PullRequestState.open


def test_reanalyze_command_enqueues_forced(db: Session) -> None:
    from unittest.mock import patch

    repo, _, _, _ = _build_pr_with_delivered_fix(db)
    with patch(
        "app.services.github.event_handlers.enqueue_workflow_analysis"
    ) as enqueue:
        eh.handle_issue_command(db, repo, ["reanalyze"])
    enqueue.assert_called_once()
    assert enqueue.call_args.kwargs["force"] is True


def test_ignore_command_mutes_by_fingerprint(db: Session) -> None:
    repo, _, _, issue = _build_pr_with_delivered_fix(db)
    assert issue.fingerprint is not None

    eh.handle_issue_command(db, repo, ["ignore", issue.fingerprint])
    db.refresh(issue)
    assert issue.ignored_at is not None

    eh.handle_issue_command(db, repo, ["unignore", issue.fingerprint])
    db.refresh(issue)
    assert issue.ignored_at is None


def test_ci_status_from_conclusion_mapping() -> None:
    assert eh.ci_status_from_conclusion("in_progress", None) == CIStatus.pending
    assert eh.ci_status_from_conclusion("completed", "success") == CIStatus.success
    assert eh.ci_status_from_conclusion("completed", "failure") == CIStatus.failure
    assert eh.ci_status_from_conclusion("completed", "neutral") == CIStatus.none


def test_review_state_to_decision_mapping() -> None:
    assert eh.review_state_to_decision("approved") == ReviewDecision.approved
    assert (
        eh.review_state_to_decision("changes_requested")
        == ReviewDecision.changes_requested
    )
    assert eh.review_state_to_decision("dismissed") == ReviewDecision.review_required
    assert eh.review_state_to_decision("commented") is None


def test_unmatched_pr_lifecycle_still_publishes_when_no_fix(db: Session) -> None:
    # A PR with no linked fix must still advance state without error.
    org = Organization(name=f"eh-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(org)
    db.commit()
    db.refresh(org)
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"eh/repo-{uuid.uuid4().hex[:8]}",
        default_branch="main",
        enabled=True,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch=f"greensecops/eh-{uuid.uuid4().hex[:8]}",
        pr_url=f"https://github.com/{repo.full_name}/pull/9",
        pr_state=PullRequestState.open,
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    eh.handle_pull_request_lifecycle(db, pr, "merge")
    db.refresh(pr)
    assert pr.pr_state == PullRequestState.merged
    assert not list(
        db.exec(select(WorkflowFix).where(WorkflowFix.pr_id == pr.id)).all()
    )
