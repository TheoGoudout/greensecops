"""Unit tests for the fix delivery Celery task (closed-PR guard, comment mode)."""

import uuid
from unittest.mock import AsyncMock, patch

from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    Fix,
    FixDeliveryMode,
    FixStatus,
    LLMProvider,
    Organization,
    PullRequest,
    PullRequestState,
    Repository,
    UserTier,
    WorkflowFile,
)
from app.services.github.fix_delivery import FixDeliveryResult
from app.workers.tasks.fix_delivery import deliver_fixes_batch

_FULL_CONTENT = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n"


def _build_ready_fix(db: Session) -> tuple[Repository, Fix]:
    org = Organization(name=f"deliv-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(org)
    db.commit()
    db.refresh(org)

    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"deliv/repo-{uuid.uuid4().hex[:8]}",
        installation_id=50001,
        default_branch="main",
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/deliv.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\n",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)

    fix = Fix(
        workflow_file_id=wf.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.ready,
        full_content=_FULL_CONTENT,
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)
    return repo, fix


def test_closed_pr_guard_rejects_and_links_fix_to_pr(db: Session) -> None:
    repo, fix = _build_ready_fix(db)
    branch = f"greensecops/fixes-{uuid.uuid4().hex[:8]}"
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch=branch,
        pr_url=f"https://github.com/{repo.full_name}/pull/7",
        pr_state="closed",
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    result = deliver_fixes_batch(
        fix_ids=[str(fix.id)],
        repo_id=str(repo.id),
        pr_branch=branch,
        pr_title="t",
        pr_body="b",
    )

    assert result == {"status": "skipped", "reason": "pr_previously_closed"}
    db.refresh(fix)
    assert fix.status == FixStatus.superseded_by_closed_pr
    # The fix is linked to the closed PR so the UI can offer regeneration,
    # and delivered_at stays unset so the rejection is recognizable as a
    # guard rejection (vs. an actually delivered fix).
    assert fix.pr_id == pr.id
    assert fix.delivered_at is None


def test_comment_mode_posts_comment_and_marks_delivered(db: Session) -> None:
    repo, fix = _build_ready_fix(db)
    repo.fix_delivery_mode = FixDeliveryMode.comment
    db.add(repo)
    db.commit()

    comment_url = f"https://github.com/{repo.full_name}/commit/abc#c1"
    with patch(
        "app.workers.tasks.fix_delivery._post_comment",
        new=AsyncMock(return_value=FixDeliveryResult(comment_url=comment_url)),
    ) as mock_post:
        result = deliver_fixes_batch(
            fix_ids=[str(fix.id)],
            repo_id=str(repo.id),
            pr_branch="ignored-in-comment-mode",
            pr_title="t",
            pr_body="b",
        )

    assert result == {"status": "ok"}
    mock_post.assert_awaited_once()
    db.refresh(fix)
    assert fix.status == FixStatus.delivered
    assert fix.delivered_at is not None
    # The comment URL is persisted on a per-repo record the fix links to.
    pr = db.get(PullRequest, fix.pr_id)
    assert pr is not None
    assert pr.comment_url == comment_url
    assert pr.pr_url is None


def test_comment_mode_delivery_failure_marks_failed(db: Session) -> None:
    repo, fix = _build_ready_fix(db)
    repo.fix_delivery_mode = FixDeliveryMode.comment
    db.add(repo)
    db.commit()

    with patch(
        "app.workers.tasks.fix_delivery._post_comment",
        new=AsyncMock(return_value=FixDeliveryResult(error="boom")),
    ):
        result = deliver_fixes_batch(
            fix_ids=[str(fix.id)],
            repo_id=str(repo.id),
            pr_branch="ignored",
            pr_title="t",
            pr_body="b",
        )

    assert result == {"status": "failed"}
    db.refresh(fix)
    assert fix.status == FixStatus.failed
    assert fix.error_message == "boom"
    # No comment record was created.
    records = db.exec(select(PullRequest).where(PullRequest.repo_id == repo.id)).all()
    assert records == []


def _make_external(db: Session, repo: Repository) -> None:
    repo.installation_id = None
    repo.is_external = True
    db.add(repo)
    db.commit()


def test_external_repo_routes_to_forked_delivery(db: Session) -> None:
    repo, fix = _build_ready_fix(db)
    _make_external(db, repo)
    branch = f"greensecops/fixes-{uuid.uuid4().hex[:8]}"
    pr_url = f"https://github.com/{repo.full_name}/pull/9"

    with (
        patch.object(settings, "GITHUB_BOT_TOKEN", "bot-tok"),
        patch(
            "app.workers.tasks.fix_delivery._deliver_batch_forked",
            new=AsyncMock(return_value=FixDeliveryResult(pr_url=pr_url)),
        ) as mock_forked,
        patch(
            "app.workers.tasks.fix_delivery._deliver_batch",
            new=AsyncMock(),
        ) as mock_direct,
    ):
        result = deliver_fixes_batch(
            fix_ids=[str(fix.id)],
            repo_id=str(repo.id),
            pr_branch=branch,
            pr_title="t",
            pr_body="b",
        )

    assert result == {"status": "ok"}
    # External repos go through the fork path, never the direct installation path.
    mock_forked.assert_awaited_once()
    mock_direct.assert_not_awaited()
    db.refresh(fix)
    assert fix.status == FixStatus.delivered
    pr = db.get(PullRequest, fix.pr_id)
    assert pr is not None
    assert pr.pr_url == pr_url


def test_external_repo_without_bot_token_skipped(db: Session) -> None:
    repo, fix = _build_ready_fix(db)
    _make_external(db, repo)

    with patch.object(settings, "GITHUB_BOT_TOKEN", None):
        result = deliver_fixes_batch(
            fix_ids=[str(fix.id)],
            repo_id=str(repo.id),
            pr_branch="greensecops/fixes-x",
            pr_title="t",
            pr_body="b",
        )

    assert result == {"status": "skipped", "reason": "no_bot_credential"}
    db.refresh(fix)
    # The fix stays ready (untouched) so it can deliver once a credential exists.
    assert fix.status == FixStatus.ready


def test_forced_delivery_clears_externally_modified_and_reopens_closed_pr(
    db: Session,
) -> None:
    repo, fix = _build_ready_fix(db)
    branch = f"greensecops/fixes-{uuid.uuid4().hex[:8]}"
    pr_url = f"https://github.com/{repo.full_name}/pull/11"
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch=branch,
        pr_url=pr_url,
        pr_state="closed",
        externally_modified=True,
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    with patch(
        "app.workers.tasks.fix_delivery._deliver_batch",
        new=AsyncMock(return_value=FixDeliveryResult(pr_url=pr_url)),
    ):
        result = deliver_fixes_batch(
            fix_ids=[str(fix.id)],
            repo_id=str(repo.id),
            pr_branch=branch,
            pr_title="t",
            pr_body="b",
            force=True,
        )

    assert result == {"status": "ok"}
    db.refresh(pr)
    # Forced redelivery onto a closed PR reopens the record through the
    # machine, and the explicit override lifts the auto-redelivery block.
    assert pr.pr_state == PullRequestState.open
    assert pr.externally_modified is False
    db.refresh(fix)
    assert fix.status == FixStatus.delivered


def test_unforced_redelivery_keeps_externally_modified(db: Session) -> None:
    repo, fix = _build_ready_fix(db)
    branch = f"greensecops/fixes-{uuid.uuid4().hex[:8]}"
    pr_url = f"https://github.com/{repo.full_name}/pull/12"
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch=branch,
        pr_url=pr_url,
        pr_state="open",
        externally_modified=True,
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    with patch(
        "app.workers.tasks.fix_delivery._deliver_batch",
        new=AsyncMock(return_value=FixDeliveryResult(pr_url=pr_url)),
    ):
        result = deliver_fixes_batch(
            fix_ids=[str(fix.id)],
            repo_id=str(repo.id),
            pr_branch=branch,
            pr_title="t",
            pr_body="b",
        )

    assert result == {"status": "ok"}
    db.refresh(pr)
    assert pr.pr_state == PullRequestState.open
    # Only a *forced* delivery clears the user-edit flag.
    assert pr.externally_modified is True
