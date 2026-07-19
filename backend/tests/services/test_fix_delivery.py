"""Tests for the fix-branch overwrite safety check in fix_delivery."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from github.GithubException import GithubException

from app.services.github.fix_delivery import (
    STALE_CONTENT_ERROR_CODE,
    USER_COMMITS_ERROR_CODE,
    FixDeliveryService,
    _DeliveryAborted,
    _is_bot_login,
    _prepare_fix_branch,
    _remove_outdated_workflow_files,
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


# ─── _remove_outdated_workflow_files ─────────────────────────────────────────


def _cf(path: str, sha: str = "sha") -> MagicMock:
    """Build a fake ContentFile with the fields the helpers read."""
    cf = MagicMock()
    cf.path = path
    cf.name = path.rsplit("/", 1)[-1]
    cf.sha = sha
    return cf


def _workflow_getter(files_by_ref: dict[str, list | GithubException]):
    """Build a get_contents side_effect that serves both directory listings
    (keyed by ref) and single-file lookups (for _upsert_file)."""

    def _get_contents(path: str, ref: str | None = None):
        if path == ".github/workflows":
            result = files_by_ref.get(ref)
            if isinstance(result, GithubException):
                raise result
            if result is None:
                raise GithubException(404, {}, None)
            return result
        # Single-file lookup done by _upsert_file; return an updatable stub.
        stub = MagicMock()
        stub.sha = "file-sha"
        return stub

    return _get_contents


def test_list_and_remove_deletes_files_absent_on_base() -> None:
    repo = MagicMock()
    repo.get_contents.side_effect = _workflow_getter(
        {
            "main": [_cf(".github/workflows/a.yml")],
            "fix": [
                _cf(".github/workflows/a.yml"),
                _cf(".github/workflows/b.yml", "b-sha"),
            ],
        }
    )

    removed = _remove_outdated_workflow_files(repo, repo, "fix", "main")

    assert removed == [".github/workflows/b.yml"]
    repo.delete_file.assert_called_once_with(
        path=".github/workflows/b.yml",
        message="chore: remove .github/workflows/b.yml deleted from main",
        sha="b-sha",
        branch="fix",
    )


def test_remove_outdated_noop_when_branch_subset_of_base() -> None:
    repo = MagicMock()
    repo.get_contents.side_effect = _workflow_getter(
        {
            "main": [
                _cf(".github/workflows/a.yml"),
                _cf(".github/workflows/b.yml"),
            ],
            "fix": [_cf(".github/workflows/a.yml")],
        }
    )

    removed = _remove_outdated_workflow_files(repo, repo, "fix", "main")

    assert removed == []
    repo.delete_file.assert_not_called()


def test_remove_outdated_ignores_non_workflow_yaml_extensions() -> None:
    # A README under the workflows dir is not a *.yml/*.yaml file and must be
    # left untouched even though it is absent from base.
    repo = MagicMock()
    repo.get_contents.side_effect = _workflow_getter(
        {
            "main": [_cf(".github/workflows/a.yml")],
            "fix": [
                _cf(".github/workflows/a.yml"),
                _cf(".github/workflows/README.md"),
            ],
        }
    )

    removed = _remove_outdated_workflow_files(repo, repo, "fix", "main")

    assert removed == []
    repo.delete_file.assert_not_called()


def test_remove_outdated_treats_missing_base_dir_as_empty() -> None:
    # Base branch has no .github/workflows dir at all (404): every workflow file
    # on the branch is outdated and removed.
    repo = MagicMock()
    repo.get_contents.side_effect = _workflow_getter(
        {
            "main": GithubException(404, {}, None),
            "fix": [_cf(".github/workflows/a.yml", "a-sha")],
        }
    )

    removed = _remove_outdated_workflow_files(repo, repo, "fix", "main")

    assert removed == [".github/workflows/a.yml"]
    repo.delete_file.assert_called_once()


def test_remove_outdated_reraises_non_404_listing_error() -> None:
    repo = MagicMock()
    repo.get_contents.side_effect = _workflow_getter(
        {"main": GithubException(500, {}, None)}
    )

    with pytest.raises(GithubException):
        _remove_outdated_workflow_files(repo, repo, "fix", "main")


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


def test_update_pr_removes_workflow_file_deleted_on_base() -> None:
    # An open PR is updated in place; a workflow file that the branch still
    # modifies but the user deleted from base is dropped from the branch first,
    # so the PR does not carry a modify/delete conflict.
    repo = _make_repo(head_sha="head1", author_login="alice")
    repo.get_branch.return_value.commit.sha = "base1"
    repo.get_pulls.return_value = [MagicMock(html_url="https://x/pull/134")]
    repo.get_contents.side_effect = _workflow_getter(
        {
            "main": [_cf(".github/workflows/wf.yml")],
            "greensecops/fixes-abc": [
                _cf(".github/workflows/wf.yml"),
                _cf(".github/workflows/old.yml", "old-sha"),
            ],
        }
    )

    with patch("app.services.github.fix_delivery.Github") as mock_github_cls:
        mock_github_cls.return_value.get_repo.return_value = repo
        svc = FixDeliveryService(app_client=_make_app_client())
        result = asyncio.run(
            svc.update_or_create_workflow_action_pr(
                installation_id=1,
                full_name="org/repo",
                base_branch="main",
                fix_branch="greensecops/fixes-abc",
                file_changes=[(".github/workflows/wf.yml", "content")],
                pr_title="title",
                pr_body="body",
            )
        )

    assert result.error is None
    repo.delete_file.assert_called_once_with(
        path=".github/workflows/old.yml",
        message="chore: remove .github/workflows/old.yml deleted from main",
        sha="old-sha",
        branch="greensecops/fixes-abc",
    )
    repo.get_git_ref.return_value.edit.assert_not_called()
    repo.create_pull.assert_not_called()


def test_create_pr_skips_outdated_removal_when_no_open_pr() -> None:
    # With no open PR the branch is reset to base, so there is nothing stale to
    # remove — the removal step must not run (no delete_file calls).
    repo = _make_repo(head_sha="head1", author_login="greensecops-staging[bot]")
    repo.get_branch.return_value.commit.sha = "base1"
    repo.get_pulls.return_value = []
    repo.create_pull.return_value.html_url = "https://x/pull/136"
    repo.get_contents.side_effect = _workflow_getter(
        {
            "main": [_cf(".github/workflows/wf.yml")],
            "greensecops/fixes-abc": [
                _cf(".github/workflows/wf.yml"),
                _cf(".github/workflows/old.yml"),
            ],
        }
    )

    with patch("app.services.github.fix_delivery.Github") as mock_github_cls:
        mock_github_cls.return_value.get_repo.return_value = repo
        svc = FixDeliveryService(app_client=_make_app_client())
        result = asyncio.run(
            svc.update_or_create_workflow_action_pr(
                installation_id=1,
                full_name="org/repo",
                base_branch="main",
                fix_branch="greensecops/fixes-abc",
                file_changes=[(".github/workflows/wf.yml", "content")],
                pr_title="title",
                pr_body="body",
            )
        )

    assert result.error is None
    repo.delete_file.assert_not_called()
    repo.create_pull.assert_called_once()


# ─── _update_or_create_open_pr (cross-repo head) ─────────────────────────────


def test_update_or_create_open_pr_uses_cross_repo_head() -> None:
    repo = MagicMock()
    repo.create_pull.return_value.html_url = "https://github.com/up/stream/pull/1"

    url = _update_or_create_open_pr(
        repo,
        [],
        "greensecops/fixes-abc",
        "main",
        "t",
        "b",
        updated_paths=["wf.yml"],
        head="bot:greensecops/fixes-abc",
    )

    assert url == "https://github.com/up/stream/pull/1"
    repo.create_pull.assert_called_once_with(
        title="t", body="b", head="bot:greensecops/fixes-abc", base="main"
    )


# ─── update_or_create_forked_pr (external outreach) ─────────────────────────

BOT_ACCOUNT = "greensecops-bot"


def _make_forked_app_client(bot: MagicMock, fork: MagicMock) -> MagicMock:
    client = MagicMock()
    client.get_bot_login = AsyncMock(return_value=BOT_ACCOUNT)
    client.get_bot_github = MagicMock(return_value=bot)
    client.ensure_fork = MagicMock(return_value=fork)
    return client


def test_forked_pr_creates_cross_repo_pr_when_none_open() -> None:
    # Branch does not exist on the fork yet ⇒ created at the upstream base SHA.
    fork = _make_repo(head_sha=None, author_login=None)
    upstream = MagicMock()
    upstream.get_branch.return_value.commit.sha = "base1"
    upstream.get_pulls.return_value = []
    upstream.create_pull.return_value.html_url = (
        "https://github.com/facebook/react/pull/42"
    )
    bot = MagicMock()
    bot.get_repo.return_value = upstream

    svc = FixDeliveryService(app_client=_make_forked_app_client(bot, fork))
    result = asyncio.run(
        svc.update_or_create_forked_pr(
            full_name="facebook/react",
            base_branch="main",
            fix_branch="greensecops/fixes-abc",
            file_changes=[("wf.yml", "content")],
            pr_title="title",
            pr_body="body",
        )
    )

    assert result.error is None
    assert result.pr_url == "https://github.com/facebook/react/pull/42"
    svc._app.ensure_fork.assert_called_once_with(bot, "facebook/react")
    # Fix branch is created on the fork at the upstream base SHA.
    fork.create_git_ref.assert_called_once_with(
        ref="refs/heads/greensecops/fixes-abc", sha="base1"
    )
    # PR is opened on the upstream from the fork branch (cross-repo head format).
    upstream.get_pulls.assert_called_once_with(
        state="open", head="greensecops-bot:greensecops/fixes-abc", base="main"
    )
    upstream.create_pull.assert_called_once_with(
        title="title",
        body="body",
        head="greensecops-bot:greensecops/fixes-abc",
        base="main",
    )


def test_forked_pr_updates_existing_pr_without_resetting_branch() -> None:
    # An already-open cross-repo PR must be updated in place; resetting the
    # fork branch would auto-close it (same invariant as the same-repo path).
    fork = _make_repo(head_sha="head1", author_login=BOT_ACCOUNT)
    upstream = MagicMock()
    upstream.get_branch.return_value.commit.sha = "base1"
    existing_pr = MagicMock(html_url="https://github.com/facebook/react/pull/7")
    upstream.get_pulls.return_value = [existing_pr]
    bot = MagicMock()
    bot.get_repo.return_value = upstream

    svc = FixDeliveryService(app_client=_make_forked_app_client(bot, fork))
    result = asyncio.run(
        svc.update_or_create_forked_pr(
            full_name="facebook/react",
            base_branch="main",
            fix_branch="greensecops/fixes-abc",
            file_changes=[("wf.yml", "content")],
            pr_title="title",
            pr_body="body",
        )
    )

    assert result.pr_url == "https://github.com/facebook/react/pull/7"
    fork.get_git_ref.return_value.edit.assert_not_called()
    existing_pr.edit.assert_called_once_with(body="body")
    upstream.create_pull.assert_not_called()


def test_forked_pr_update_removes_workflow_file_deleted_on_upstream() -> None:
    # Cross-repo update: the fix branch lives on the fork, but the base state is
    # read from the upstream. A workflow file deleted upstream is dropped from
    # the fork branch before the upstream PR is updated in place.
    fork = _make_repo(head_sha="head1", author_login=BOT_ACCOUNT)
    fork.get_contents.side_effect = _workflow_getter(
        {
            "greensecops/fixes-abc": [
                _cf(".github/workflows/wf.yml"),
                _cf(".github/workflows/old.yml", "old-sha"),
            ],
        }
    )
    upstream = MagicMock()
    upstream.get_branch.return_value.commit.sha = "base1"
    upstream.get_pulls.return_value = [MagicMock(html_url="https://x/pull/7")]
    upstream.get_contents.side_effect = _workflow_getter(
        {"main": [_cf(".github/workflows/wf.yml")]}
    )
    bot = MagicMock()
    bot.get_repo.return_value = upstream

    svc = FixDeliveryService(app_client=_make_forked_app_client(bot, fork))
    result = asyncio.run(
        svc.update_or_create_forked_pr(
            full_name="facebook/react",
            base_branch="main",
            fix_branch="greensecops/fixes-abc",
            file_changes=[(".github/workflows/wf.yml", "content")],
            pr_title="title",
            pr_body="body",
        )
    )

    assert result.error is None
    fork.delete_file.assert_called_once_with(
        path=".github/workflows/old.yml",
        message="chore: remove .github/workflows/old.yml deleted from main",
        sha="old-sha",
        branch="greensecops/fixes-abc",
    )
    fork.get_git_ref.return_value.edit.assert_not_called()
    upstream.create_pull.assert_not_called()


def test_forked_pr_aborts_on_stale_base_content() -> None:
    fork = _make_repo(head_sha=None, author_login=None)
    upstream = MagicMock()
    upstream.get_branch.return_value.commit.sha = "base1"
    upstream.get_pulls.return_value = []
    # Upstream base file now differs from what the fix was generated against.
    stale = MagicMock()
    stale.decoded_content = b"changed upstream"
    upstream.get_contents.return_value = stale
    bot = MagicMock()
    bot.get_repo.return_value = upstream

    svc = FixDeliveryService(app_client=_make_forked_app_client(bot, fork))
    result = asyncio.run(
        svc.update_or_create_forked_pr(
            full_name="facebook/react",
            base_branch="main",
            fix_branch="greensecops/fixes-abc",
            file_changes=[("wf.yml", "content")],
            pr_title="title",
            pr_body="body",
            expected_base_contents={"wf.yml": "original content"},
        )
    )

    assert result.error_code == STALE_CONTENT_ERROR_CODE
    upstream.create_pull.assert_not_called()
