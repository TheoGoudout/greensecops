"""Tests for the fix-branch overwrite safety check in fix_delivery."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from github.GithubException import GithubException

from app.services.github.fix_delivery import (
    USER_COMMITS_ERROR_CODE,
    FixDeliveryService,
    _DeliveryAborted,
    _is_bot_login,
    _prepare_fix_branch,
    _update_or_create_open_pr,
)

BOT_LOGIN = "greensecops-staging[bot]"


# ─── _is_bot_login ───────────────────────────────────────────────────────────


def test_is_bot_login_matches_derived_app_login() -> None:
    # The staging app's own commits must be recognized even though the
    # configured GITHUB_BOT_HANDLE (@greensecops) has no -staging suffix.
    assert _is_bot_login("greensecops-staging[bot]", BOT_LOGIN) is True


def test_is_bot_login_matches_configured_handle() -> None:
    # The configured handle is still accepted (union), e.g. a prod-authored branch.
    assert _is_bot_login("greensecops[bot]", BOT_LOGIN) is True


def test_is_bot_login_rejects_human() -> None:
    assert _is_bot_login("alice", BOT_LOGIN) is False


def test_is_bot_login_permissive_on_unknown_author() -> None:
    assert _is_bot_login(None, BOT_LOGIN) is True


# ─── _prepare_fix_branch ─────────────────────────────────────────────────────


def _make_repo(head_sha: str | None, author_login: str | None) -> MagicMock:
    """Build a fake repo. ``head_sha=None`` means the branch does not exist."""
    repo = MagicMock()
    if head_sha is None:
        repo.get_git_ref.side_effect = GithubException(404, {}, None)
    else:
        branch_ref = MagicMock()
        branch_ref.object.sha = head_sha
        repo.get_git_ref.return_value = branch_ref
        author = MagicMock()
        author.login = author_login
        commit = MagicMock()
        commit.author = author if author_login is not None else None
        repo.get_commit.return_value = commit
    return repo


def test_prepare_fix_branch_creates_when_missing() -> None:
    repo = _make_repo(head_sha=None, author_login=None)

    _prepare_fix_branch(
        repo, "greensecops/fixes-abc", "base1", False, BOT_LOGIN, reset_to_base=True
    )

    repo.create_git_ref.assert_called_once_with(
        ref="refs/heads/greensecops/fixes-abc", sha="base1"
    )


def test_prepare_fix_branch_resets_bot_authored_branch() -> None:
    repo = _make_repo(head_sha="head1", author_login="greensecops-staging[bot]")

    _prepare_fix_branch(
        repo, "greensecops/fixes-abc", "base1", False, BOT_LOGIN, reset_to_base=True
    )

    repo.get_git_ref.return_value.edit.assert_called_once_with(sha="base1", force=True)


def test_prepare_fix_branch_aborts_on_human_commits() -> None:
    repo = _make_repo(head_sha="head1", author_login="alice")

    with pytest.raises(_DeliveryAborted) as exc:
        _prepare_fix_branch(
            repo, "greensecops/fixes-abc", "base1", False, BOT_LOGIN, reset_to_base=True
        )

    assert exc.value.code == USER_COMMITS_ERROR_CODE
    repo.get_git_ref.return_value.edit.assert_not_called()


def test_prepare_fix_branch_override_skips_check() -> None:
    repo = _make_repo(head_sha="head1", author_login="alice")

    _prepare_fix_branch(
        repo, "greensecops/fixes-abc", "base1", True, BOT_LOGIN, reset_to_base=True
    )

    repo.get_commit.assert_not_called()
    repo.get_git_ref.return_value.edit.assert_called_once_with(sha="base1", force=True)


def test_prepare_fix_branch_skips_reset_when_pr_already_open() -> None:
    # Regression: an open PR's branch must never be force-reset to base, even
    # for a branch with human commits that would otherwise abort the reset —
    # reset_to_base=False means "don't touch the branch at all", full stop.
    # Resetting an open PR's head to be even with base makes GitHub
    # auto-close the PR before the new fix commits land (bug: closed PR
    # #134, opened a new PR #135 instead of updating #134).
    repo = _make_repo(head_sha="head1", author_login="alice")

    _prepare_fix_branch(
        repo, "greensecops/fixes-abc", "base1", False, BOT_LOGIN, reset_to_base=False
    )

    repo.get_commit.assert_not_called()
    repo.get_git_ref.return_value.edit.assert_not_called()


# ─── _update_or_create_open_pr ───────────────────────────────────────────────


def test_update_or_create_open_pr_reuses_existing_pr() -> None:
    repo = MagicMock()
    existing_pr = MagicMock(html_url="https://github.com/org/repo/pull/134")

    url = _update_or_create_open_pr(
        repo,
        [existing_pr],
        "greensecops/fixes-abc",
        "main",
        "title",
        "body",
        updated_paths=["wf.yml"],
    )

    assert url == "https://github.com/org/repo/pull/134"
    existing_pr.edit.assert_called_once_with(body="body")
    existing_pr.create_issue_comment.assert_called_once()
    assert "wf.yml" in existing_pr.create_issue_comment.call_args.args[0]
    repo.create_pull.assert_not_called()


def test_update_or_create_open_pr_comment_lists_all_updated_paths() -> None:
    repo = MagicMock()
    existing_pr = MagicMock(html_url="https://github.com/org/repo/pull/134")

    _update_or_create_open_pr(
        repo,
        [existing_pr],
        "greensecops/fixes-abc",
        "main",
        "title",
        "body",
        updated_paths=["b.yml", "a.yml"],
    )

    comment = existing_pr.create_issue_comment.call_args.args[0]
    assert "a.yml" in comment
    assert "b.yml" in comment


def test_update_or_create_open_pr_creates_when_none_open() -> None:
    repo = MagicMock()
    repo.create_pull.return_value.html_url = "https://github.com/org/repo/pull/135"

    url = _update_or_create_open_pr(
        repo,
        [],
        "greensecops/fixes-abc",
        "main",
        "title",
        "body",
        updated_paths=["wf.yml"],
    )

    assert url == "https://github.com/org/repo/pull/135"
    repo.create_pull.assert_called_once_with(
        title="title", body="body", head="greensecops/fixes-abc", base="main"
    )


# ─── update_or_create_workflow_action_pr (integration) ──────────────────────


def _make_app_client() -> MagicMock:
    client = MagicMock()
    client.get_installation_token = AsyncMock(return_value="token")
    client.get_app_bot_login = AsyncMock(return_value=BOT_LOGIN)
    return client


def test_update_or_create_workflow_action_pr_skips_reset_when_pr_open() -> None:
    # Regression test for the bug: PR #134 was open on a branch with a human
    # commit on top of an earlier bot commit. Delivering a new fix reset the
    # branch to base (force-push), which GitHub read as "nothing left to
    # merge" and auto-closed #134; the subsequent PR search then found no
    # open PR and created #135 instead of updating #134.
    repo = _make_repo(head_sha="head1", author_login="alice")
    repo.get_branch.return_value.commit.sha = "base1"
    existing_pr = MagicMock(html_url="https://github.com/org/repo/pull/134")
    repo.get_pulls.return_value = [existing_pr]

    with patch("app.services.github.fix_delivery.Github") as mock_github_cls:
        mock_github_cls.return_value.get_repo.return_value = repo
        svc = FixDeliveryService(app_client=_make_app_client())
        result = asyncio.run(
            svc.update_or_create_workflow_action_pr(
                installation_id=1,
                full_name="org/repo",
                base_branch="main",
                fix_branch="greensecops/fixes-abc",
                file_changes=[("wf.yml", "content")],
                pr_title="title",
                pr_body="body",
            )
        )

    assert result.error is None
    assert result.pr_url == "https://github.com/org/repo/pull/134"
    repo.get_git_ref.return_value.edit.assert_not_called()
    existing_pr.edit.assert_called_once_with(body="body")
    repo.create_pull.assert_not_called()
    # The re-analysis comment names the workflow file that changed.
    assert "wf.yml" in existing_pr.create_issue_comment.call_args.args[0]


def test_update_or_create_workflow_action_pr_resets_when_no_open_pr() -> None:
    # Non-regression: reusing a stale bot-authored branch with no open PR
    # (e.g. after a prior PR was merged or rejected) still rebases onto base.
    repo = _make_repo(head_sha="head1", author_login="greensecops-staging[bot]")
    repo.get_branch.return_value.commit.sha = "base1"
    repo.get_pulls.return_value = []
    repo.create_pull.return_value.html_url = "https://github.com/org/repo/pull/136"

    with patch("app.services.github.fix_delivery.Github") as mock_github_cls:
        mock_github_cls.return_value.get_repo.return_value = repo
        svc = FixDeliveryService(app_client=_make_app_client())
        result = asyncio.run(
            svc.update_or_create_workflow_action_pr(
                installation_id=1,
                full_name="org/repo",
                base_branch="main",
                fix_branch="greensecops/fixes-abc",
                file_changes=[("wf.yml", "content")],
                pr_title="title",
                pr_body="body",
            )
        )

    assert result.error is None
    assert result.pr_url == "https://github.com/org/repo/pull/136"
    repo.get_git_ref.return_value.edit.assert_called_once_with(sha="base1", force=True)
    repo.create_pull.assert_called_once()
