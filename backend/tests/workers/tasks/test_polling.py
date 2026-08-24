"""Unit tests for the external-repo poller.

The poller is only a *source*: it fetches REST snapshots and routes them through
the shared ``event_handlers`` (covered by ``tests/services/test_event_handlers``).
These tests mock the GitHub client and assert the poller turns a snapshot diff
into the right handler calls — so an external repo is reconciled by the same
code a webhook would run.
"""

import uuid
from unittest.mock import patch

from sqlmodel import Session

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
from app.services.github.app_client import PRSnapshot
from app.workers.tasks import polling


def _external_repo(db: Session, *, head_sha: str | None = None) -> Repository:
    org = Organization(name=f"poll-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(org)
    db.commit()
    db.refresh(org)
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"poll/repo-{uuid.uuid4().hex[:8]}",
        installation_id=None,
        is_external=True,
        default_branch="main",
        enabled=True,
        last_polled_head_sha=head_sha,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo


def _open_pr(
    db: Session, repo: Repository, *, head_sha: str | None = None
) -> PullRequest:
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch=f"greensecops/poll-{uuid.uuid4().hex[:8]}",
        pr_url=f"https://github.com/{repo.full_name}/pull/3",
        pr_state=PullRequestState.open,
        head_sha=head_sha,
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)
    return pr


def _delivered_fix_with_issue(
    db: Session, repo: Repository, pr: PullRequest
) -> tuple[WorkflowFix, WorkflowFinding]:
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
        slug=f"poll_rule_{uuid.uuid4().hex[:8]}",
        category=Category.security,
        severity=Severity.high,
        title="t",
        description="d",
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
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
    return fix, issue


def _snapshot(**kwargs: object) -> PRSnapshot:
    defaults: dict[str, object] = {
        "state": PullRequestState.open,
        "merged": False,
        "draft": False,
        "head_sha": "sha-open",
        "mergeable_state": "clean",
        "ci_status": None,
        "review_decision": None,
    }
    defaults.update(kwargs)
    return PRSnapshot(**defaults)  # type: ignore[arg-type]


def _poll_data(
    branch: str | None,
    head_sha: str | None,
    prs: dict[uuid.UUID, polling._PRPollResult],
) -> polling._RepoPollData:
    return polling._RepoPollData(branch=branch, head_sha=head_sha, prs=prs)


def test_head_advance_enqueues_polled_analysis(db: Session) -> None:
    repo = _external_repo(db, head_sha="old-sha")
    data = _poll_data("main", "new-sha", {})

    # Capture args while the poller's session is still open (the repo object is
    # detached once _poll_repository_impl returns).
    calls: list[tuple] = []

    def _record(repo_arg, branch, sha, trigger, force=False):
        calls.append((str(repo_arg.id), branch, sha, trigger, force))

    with (
        patch("app.workers.tasks.polling._fetch_repo_poll_data", return_value=data),
        patch(
            "app.services.github.event_handlers.enqueue_workflow_analysis",
            side_effect=_record,
        ),
    ):
        result = polling._poll_repository_impl(str(repo.id))

    assert calls == [(str(repo.id), "main", "new-sha", ScanTrigger.polled_push, False)]
    assert result["analyses_enqueued"] == 1
    db.refresh(repo)
    assert repo.last_polled_head_sha == "new-sha"


def test_first_poll_is_baseline_no_analysis(db: Session) -> None:
    repo = _external_repo(db, head_sha=None)
    data = _poll_data("main", "first-sha", {})

    with (
        patch("app.workers.tasks.polling._fetch_repo_poll_data", return_value=data),
        patch(
            "app.services.github.event_handlers.enqueue_workflow_analysis"
        ) as enqueue,
    ):
        polling._poll_repository_impl(str(repo.id))

    enqueue.assert_not_called()
    db.refresh(repo)
    assert repo.last_polled_head_sha == "first-sha"


def test_merged_snapshot_lands_fix_and_resolves_issue(db: Session) -> None:
    repo = _external_repo(db, head_sha="head")
    pr = _open_pr(db, repo)
    fix, issue = _delivered_fix_with_issue(db, repo, pr)

    data = _poll_data(
        "main",
        "head",
        {
            pr.id: polling._PRPollResult(
                snapshot=_snapshot(state=PullRequestState.closed, merged=True),
                command_comments=[],
            )
        },
    )
    with patch("app.workers.tasks.polling._fetch_repo_poll_data", return_value=data):
        polling._poll_repository_impl(str(repo.id))

    db.refresh(pr)
    db.refresh(fix)
    db.refresh(issue)
    assert pr.pr_state == PullRequestState.merged
    assert fix.status == FixStatus.landed
    assert issue.resolution_reason == FindingResolutionReason.merged


def test_ci_and_review_snapshot_updates_columns(db: Session) -> None:
    repo = _external_repo(db, head_sha="head")
    pr = _open_pr(db, repo, head_sha="sha-open")

    data = _poll_data(
        "main",
        "head",
        {
            pr.id: polling._PRPollResult(
                snapshot=_snapshot(
                    head_sha="sha-open",
                    ci_status=CIStatus.failure,
                    review_decision=ReviewDecision.changes_requested,
                ),
                command_comments=[],
            )
        },
    )
    with patch("app.workers.tasks.polling._fetch_repo_poll_data", return_value=data):
        polling._poll_repository_impl(str(repo.id))

    db.refresh(pr)
    assert pr.ci_status == CIStatus.failure
    assert pr.review_decision == ReviewDecision.changes_requested


def test_new_commits_snapshot_triggers_sync(db: Session) -> None:
    repo = _external_repo(db, head_sha="head")
    pr = _open_pr(db, repo, head_sha="old-pr-sha")
    assert pr.updated_at is None

    data = _poll_data(
        "main",
        "head",
        {
            pr.id: polling._PRPollResult(
                snapshot=_snapshot(head_sha="new-pr-sha"),
                command_comments=[],
            )
        },
    )
    with patch("app.workers.tasks.polling._fetch_repo_poll_data", return_value=data):
        polling._poll_repository_impl(str(repo.id))

    db.refresh(pr)
    assert pr.head_sha == "new-pr-sha"
    assert pr.updated_at is not None


def test_command_comment_dispatched(db: Session) -> None:
    repo = _external_repo(db, head_sha="head")
    pr = _open_pr(db, repo, head_sha="sha-open")

    data = _poll_data(
        "main",
        "head",
        {
            pr.id: polling._PRPollResult(
                snapshot=_snapshot(head_sha="sha-open"),
                command_comments=["/greensecops reanalyze"],
            )
        },
    )
    with (
        patch("app.workers.tasks.polling._fetch_repo_poll_data", return_value=data),
        patch(
            "app.services.github.event_handlers.enqueue_workflow_analysis"
        ) as enqueue,
    ):
        polling._poll_repository_impl(str(repo.id))

    # Called once for the /greensecops reanalyze command (head unchanged, so no
    # push-triggered analysis).
    enqueue.assert_called_once()
    assert enqueue.call_args.kwargs["force"] is True
    db.refresh(pr)
    assert pr.last_polled_comment_at is not None


def test_disabled_repo_is_skipped(db: Session) -> None:
    repo = _external_repo(db)
    repo.enabled = False
    db.add(repo)
    db.commit()
    result = polling._poll_repository_impl(str(repo.id))
    assert result["status"] == "skipped"


def test_poll_repositories_fans_out_external_only(db: Session) -> None:
    external = _external_repo(db)
    internal_org = Organization(name=f"o-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(internal_org)
    db.commit()
    db.refresh(internal_org)
    internal = Repository(
        org_id=internal_org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"poll/internal-{uuid.uuid4().hex[:8]}",
        installation_id=99001,
        is_external=False,
        default_branch="main",
        enabled=True,
    )
    db.add(internal)
    db.commit()

    with patch("app.workers.tasks.polling.poll_repository.apply_async") as apply_async:
        polling._poll_repositories_impl(external_only=True)

    dispatched = {c.kwargs["kwargs"]["repo_id"] for c in apply_async.call_args_list}
    assert str(external.id) in dispatched
    assert str(internal.id) not in dispatched
