"""Tests for the fix-branch overwrite safety check in fix_delivery."""

from unittest.mock import MagicMock

import pytest
from github.GithubException import GithubException

from app.services.github.fix_delivery import (
    USER_COMMITS_ERROR_CODE,
    _DeliveryAborted,
    _is_bot_login,
    _prepare_fix_branch,
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

    existed = _prepare_fix_branch(
        repo, "greensecops/fixes-abc", "base1", False, BOT_LOGIN
    )

    assert existed is False
    repo.create_git_ref.assert_called_once_with(
        ref="refs/heads/greensecops/fixes-abc", sha="base1"
    )


def test_prepare_fix_branch_resets_bot_authored_branch() -> None:
    repo = _make_repo(head_sha="head1", author_login="greensecops-staging[bot]")

    existed = _prepare_fix_branch(
        repo, "greensecops/fixes-abc", "base1", False, BOT_LOGIN
    )

    assert existed is True
    repo.get_git_ref.return_value.edit.assert_called_once_with(sha="base1", force=True)


def test_prepare_fix_branch_aborts_on_human_commits() -> None:
    repo = _make_repo(head_sha="head1", author_login="alice")

    with pytest.raises(_DeliveryAborted) as exc:
        _prepare_fix_branch(repo, "greensecops/fixes-abc", "base1", False, BOT_LOGIN)

    assert exc.value.code == USER_COMMITS_ERROR_CODE
    repo.get_git_ref.return_value.edit.assert_not_called()


def test_prepare_fix_branch_override_skips_check() -> None:
    repo = _make_repo(head_sha="head1", author_login="alice")

    existed = _prepare_fix_branch(
        repo, "greensecops/fixes-abc", "base1", True, BOT_LOGIN
    )

    assert existed is True
    repo.get_commit.assert_not_called()
    repo.get_git_ref.return_value.edit.assert_called_once_with(sha="base1", force=True)
