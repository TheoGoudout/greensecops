"""How a fix reaches a branch: rebased onto base, and never over user work."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from github.GithubException import GithubException

from app.services.github.fix_delivery import (
    NOTHING_TO_DELIVER_ERROR_CODE,
    STALE_CONTENT_ERROR_CODE,
    USER_COMMITS_ERROR_CODE,
    FixDeliveryService,
    _DeliveryAborted,
    _rebase_fix_branch,
    _update_or_create_open_pr,
    is_bot_login,
)

BOT_LOGIN = "greensecops-staging[bot]"


# ─── is_bot_login ───────────────────────────────────────────────────────────


def test_is_bot_login_matches_derived_app_login() -> None:
    # The staging app's own commits must be recognized even though the
    # configured GITHUB_BOT_HANDLE (@greensecops) has no -staging suffix.
    assert is_bot_login("greensecops-staging[bot]", BOT_LOGIN) is True


def test_is_bot_login_matches_configured_handle() -> None:
    # The configured handle is still accepted (union), e.g. a prod-authored branch.
    assert is_bot_login("greensecops[bot]", BOT_LOGIN) is True


def test_is_bot_login_rejects_human() -> None:
    assert is_bot_login("alice", BOT_LOGIN) is False


def test_is_bot_login_permissive_on_unknown_author() -> None:
    assert is_bot_login(None, BOT_LOGIN) is True


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


# ─── _rebase_fix_branch ──────────────────────────────────────────────────────


def _rebase_repo(
    *,
    head_sha: str | None = None,
    author_login: str | None = None,
    base_contents: dict[str, str] | None = None,
    modes: dict[str, str] | None = None,
) -> MagicMock:
    """A repo whose base branch holds ``base_contents``.

    ``head_sha=None`` means the fix branch does not exist yet.
    """
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

    base_contents = base_contents or {}

    def _get_contents(path: str, ref: str | None = None):  # type: ignore[no-untyped-def]
        if path not in base_contents:
            raise GithubException(404, {}, None)
        stub = MagicMock()
        stub.sha = "file-sha"
        stub.decoded_content = base_contents[path].encode()
        return stub

    repo.get_contents.side_effect = _get_contents
    repo.get_git_commit.return_value.tree.sha = "base-tree"
    tree = MagicMock()
    tree.tree = [
        SimpleNamespace(path=p, mode=m, type="blob") for p, m in (modes or {}).items()
    ]
    repo.get_git_tree.return_value = tree
    # Each created commit gets its own sha, so the chain is observable.
    created: list[MagicMock] = []

    def _create_commit(message, tree_arg, parents):  # type: ignore[no-untyped-def]
        commit = MagicMock()
        commit.sha = f"c{len(created) + 1}"
        commit.message = message
        commit.parents = parents
        created.append(commit)
        return commit

    repo.create_git_commit.side_effect = _create_commit
    repo.created_commits = created  # type: ignore[attr-defined]
    return repo


def _rebase(repo: MagicMock, file_changes, **kw):  # type: ignore[no-untyped-def]
    return _rebase_fix_branch(
        repo,
        repo,
        "greensecops/fixes-abc",
        "base1",
        file_changes,
        kw.pop("commit_messages", {}),
        kw.pop("override_user_commits", False),
        BOT_LOGIN,
    )


def test_the_new_commit_is_parented_on_the_current_base() -> None:
    """The point of the whole change.

    The branch used to be left on whatever base it was originally cut from,
    because force-pushing it *to* base auto-closes the open PR. Building the
    new history first and moving the ref once means it is never observed at
    zero commits ahead — so it can be rebased and the PR still updated in
    place.
    """
    repo = _rebase_repo(head_sha="old-head", author_login=BOT_LOGIN)
    base_commit = repo.get_git_commit.return_value

    head = _rebase(repo, [("wf.yml", "fixed")])

    repo.get_git_commit.assert_called_once_with("base1")
    assert repo.create_git_commit.call_args.args[2] == [base_commit]
    repo.get_git_ref.return_value.edit.assert_called_once_with(sha=head, force=True)


def test_several_files_become_a_chain_of_commits() -> None:
    """One commit per file, each keeping its own message — the commit subjects
    say what they fixed, which is what makes the history worth reading."""
    repo = _rebase_repo(head_sha="old-head", author_login=BOT_LOGIN)

    head = _rebase(
        repo,
        [("a.yml", "fixed a"), ("b.yml", "fixed b")],
        commit_messages={"a.yml": "Fixing 2 issues in a.yml", "b.yml": "msg b"},
    )

    messages = [c.message for c in repo.created_commits]
    assert messages == ["Fixing 2 issues in a.yml", "msg b"]
    # Second commit parents on the first, not on base.
    assert repo.created_commits[1].parents == [repo.created_commits[0]]
    assert head == repo.created_commits[-1].sha


def test_a_missing_branch_is_created_at_the_new_head() -> None:
    repo = _rebase_repo(head_sha=None)

    head = _rebase(repo, [("wf.yml", "fixed")])

    repo.create_git_ref.assert_called_once_with(
        ref="refs/heads/greensecops/fixes-abc", sha=head
    )


def test_a_file_already_matching_base_is_not_committed() -> None:
    """Rebuilding from base every time would otherwise put an empty commit on
    the PR at every redelivery."""
    repo = _rebase_repo(
        head_sha="old-head",
        author_login=BOT_LOGIN,
        base_contents={"wf.yml": "fixed\n"},
    )

    head = _rebase(repo, [("wf.yml", "fixed")])

    assert head is None
    repo.create_git_commit.assert_not_called()
    # And critically: the ref is left alone rather than reset to base, which
    # would make GitHub close an open PR as having nothing to merge.
    repo.get_git_ref.return_value.edit.assert_not_called()


def test_a_files_mode_survives_the_rewrite() -> None:
    """Read from the base tree, not assumed: rewriting a file must not
    silently drop its executable bit."""
    repo = _rebase_repo(
        head_sha="old-head",
        author_login=BOT_LOGIN,
        modes={"deploy.sh": "100755"},
    )

    _rebase(repo, [("deploy.sh", "#!/bin/sh\n")])

    element = repo.create_git_tree.call_args.args[0][0]
    assert element._identity["mode"] == "100755"


def test_a_new_file_defaults_to_a_regular_mode() -> None:
    repo = _rebase_repo(head_sha="old-head", author_login=BOT_LOGIN)

    _rebase(repo, [("new.yml", "content")])

    element = repo.create_git_tree.call_args.args[0][0]
    assert element._identity["mode"] == "100644"


def test_content_gains_a_trailing_newline() -> None:
    repo = _rebase_repo(head_sha="old-head", author_login=BOT_LOGIN)

    _rebase(repo, [("wf.yml", "no newline")])

    element = repo.create_git_tree.call_args.args[0][0]
    assert element._identity["content"] == "no newline\n"


# ─── Not over somebody's work ────────────────────────────────────────────────


def test_a_branch_with_human_commits_is_refused() -> None:
    """Every delivery force-pushes now, so this guard runs on every delivery.

    It used to run only where the code already force-pushed — which was never,
    for a branch backing an open PR. A person's commits on such a branch would
    now be destroyed, so the delivery aborts instead.
    """
    repo = _rebase_repo(head_sha="old-head", author_login="alice")

    with pytest.raises(_DeliveryAborted) as exc:
        _rebase(repo, [("wf.yml", "fixed")])

    assert exc.value.code == USER_COMMITS_ERROR_CODE
    repo.get_git_ref.return_value.edit.assert_not_called()


def test_a_bot_authored_branch_is_rebased_freely() -> None:
    repo = _rebase_repo(head_sha="old-head", author_login="greensecops[bot]")

    assert _rebase(repo, [("wf.yml", "fixed")]) is not None


def test_an_explicit_override_rebases_over_human_commits() -> None:
    """A forced redelivery is the user saying to do it anyway."""
    repo = _rebase_repo(head_sha="old-head", author_login="alice")

    assert _rebase(repo, [("wf.yml", "fixed")], override_user_commits=True) is not None


# ─── update_or_create_workflow_action_pr (integration) ───────────────────────


def _make_app_client() -> MagicMock:
    client = MagicMock()
    client.get_installation_token = AsyncMock(return_value="token")
    client.get_app_bot_login = AsyncMock(return_value=BOT_LOGIN)
    return client


def _deliver(repo: MagicMock, file_changes=(("wf.yml", "content"),)):  # type: ignore[no-untyped-def]
    with patch("app.services.github.fix_delivery.Github") as mock_github_cls:
        mock_github_cls.return_value.get_repo.return_value = repo
        svc = FixDeliveryService(app_client=_make_app_client())
        return asyncio.run(
            svc.update_or_create_workflow_action_pr(
                installation_id=1,
                full_name="org/repo",
                base_branch="main",
                fix_branch="greensecops/fixes-abc",
                file_changes=list(file_changes),
                pr_title="title",
                pr_body="body",
            )
        )


def test_an_open_pr_is_updated_in_place_after_the_rebase() -> None:
    """#134 must stay #134.

    Force-pushing the branch *to* base used to auto-close the PR (nothing left
    to merge), and the next search then found no open PR and opened #135. The
    branch now moves straight to a head already ahead of base, so the PR never
    sees zero commits ahead.
    """
    repo = _rebase_repo(head_sha="old-head", author_login=BOT_LOGIN)
    repo.get_branch.return_value.commit.sha = "base1"
    existing_pr = MagicMock(html_url="https://github.com/org/repo/pull/134")
    repo.get_pulls.return_value = [existing_pr]

    result = _deliver(repo)

    assert result.error is None
    assert result.pr_url == "https://github.com/org/repo/pull/134"
    repo.create_pull.assert_not_called()
    existing_pr.edit.assert_called_once_with(body="body")
    # Rebased, which is what it never used to be while a PR was open.
    repo.get_git_ref.return_value.edit.assert_called_once()
    assert repo.get_git_ref.return_value.edit.call_args.kwargs["force"] is True
    assert "wf.yml" in existing_pr.create_issue_comment.call_args.args[0]


def test_a_closed_pr_is_not_reopened_a_new_one_is_opened() -> None:
    """A PR the user closed stays closed.

    The search is scoped to open PRs, so a branch whose only PR was closed
    gets a fresh one rather than the closed one being revived.
    """
    repo = _rebase_repo(head_sha="old-head", author_login=BOT_LOGIN)
    repo.get_branch.return_value.commit.sha = "base1"
    repo.get_pulls.return_value = []
    repo.create_pull.return_value.html_url = "https://github.com/org/repo/pull/136"

    result = _deliver(repo)

    assert result.pr_url == "https://github.com/org/repo/pull/136"
    repo.create_pull.assert_called_once()
    assert repo.get_pulls.call_args.kwargs["state"] == "open"


def test_a_delivery_that_changes_nothing_leaves_an_open_pr_alone() -> None:
    """Resetting the branch to base here would close the PR."""
    repo = _rebase_repo(
        head_sha="old-head",
        author_login=BOT_LOGIN,
        base_contents={"wf.yml": "content\n"},
    )
    repo.get_branch.return_value.commit.sha = "base1"
    existing_pr = MagicMock(html_url="https://github.com/org/repo/pull/134")
    repo.get_pulls.return_value = [existing_pr]

    result = _deliver(repo)

    assert result.pr_url == "https://github.com/org/repo/pull/134"
    repo.get_git_ref.return_value.edit.assert_not_called()
    repo.create_pull.assert_not_called()


def test_a_delivery_that_changes_nothing_opens_no_pr() -> None:
    """There is no diff, so there is nothing to review."""
    repo = _rebase_repo(
        head_sha=None,
        base_contents={"wf.yml": "content\n"},
    )
    repo.get_branch.return_value.commit.sha = "base1"
    repo.get_pulls.return_value = []

    result = _deliver(repo)

    assert result.error_code == NOTHING_TO_DELIVER_ERROR_CODE
    repo.create_pull.assert_not_called()


def test_a_file_that_dropped_out_of_the_fix_set_needs_no_cleanup() -> None:
    """Rebuilding from the base tree is what makes the branch self-reconciling.

    A file the branch fixed in an earlier run, whose issues are now resolved,
    simply carries base content again — and a file deleted on base is simply
    absent. Both used to need a forward-only reconciliation pass to undo, which
    showed up in the PR as revert commits.
    """
    repo = _rebase_repo(head_sha="old-head", author_login=BOT_LOGIN)
    repo.get_branch.return_value.commit.sha = "base1"
    repo.get_pulls.return_value = [MagicMock(html_url="https://x/pull/134")]

    _deliver(repo, file_changes=[("still-broken.yml", "fixed")])

    # Only the file still in the fix set is written; nothing is deleted or
    # reverted, because the tree started from base.
    written = [
        call.args[0][0]._identity["path"]
        for call in repo.create_git_tree.call_args_list
    ]
    assert written == ["still-broken.yml"]
    repo.delete_file.assert_not_called()


# ─── update_or_create_forked_pr (external outreach) ──────────────────────────


# The fork's commits are authored by the bot *account* (`get_bot_login`), not
# by the App installation — a different login from `BOT_LOGIN` above.
FORK_BOT_LOGIN = "greensecops-bot"


def _make_forked_app_client(bot: MagicMock, fork: MagicMock) -> MagicMock:
    client = MagicMock()
    client.get_bot_login = AsyncMock(return_value=FORK_BOT_LOGIN)
    client.get_bot_github = MagicMock(return_value=bot)
    client.ensure_fork = MagicMock(return_value=fork)
    return client


def _deliver_forked(
    fork: MagicMock,
    upstream: MagicMock,
    expected_base_contents: dict[str, str] | None = None,
):  # type: ignore[no-untyped-def]
    bot = MagicMock()
    bot.get_repo.return_value = upstream
    svc = FixDeliveryService(app_client=_make_forked_app_client(bot, fork))
    return asyncio.run(
        svc.update_or_create_forked_pr(
            full_name="facebook/react",
            base_branch="main",
            fix_branch="greensecops/fixes-abc",
            file_changes=[("wf.yml", "content")],
            pr_title="title",
            pr_body="body",
            expected_base_contents=expected_base_contents,
        )
    )


def test_a_forked_branch_is_rebased_onto_the_upstream_base() -> None:
    """The commits live on the bot's fork but parent onto the upstream base.

    A fork shares the upstream's git objects, so no sync step is needed — and
    the resulting PR is one commit ahead of upstream rather than of whatever
    the fork happened to be on.
    """
    fork = _rebase_repo(head_sha="old-head", author_login=FORK_BOT_LOGIN)
    upstream = _rebase_repo(head_sha=None)
    upstream.get_branch.return_value.commit.sha = "base1"
    upstream.get_pulls.return_value = []
    upstream.create_pull.return_value.html_url = "https://github.com/fb/react/pull/9"

    result = _deliver_forked(fork, upstream)

    assert result.pr_url == "https://github.com/fb/react/pull/9"
    fork.get_git_commit.assert_called_once_with("base1")
    fork.get_git_ref.return_value.edit.assert_called_once()
    # The PR is opened on the upstream, from the fork's branch.
    assert upstream.create_pull.call_args.kwargs["head"] == (
        f"{FORK_BOT_LOGIN}:greensecops/fixes-abc"
    )


def test_a_forked_pr_open_upstream_is_updated_in_place() -> None:
    fork = _rebase_repo(head_sha="old-head", author_login=FORK_BOT_LOGIN)
    upstream = _rebase_repo(head_sha=None)
    upstream.get_branch.return_value.commit.sha = "base1"
    existing = MagicMock(html_url="https://github.com/fb/react/pull/9")
    upstream.get_pulls.return_value = [existing]

    result = _deliver_forked(fork, upstream)

    assert result.pr_url == "https://github.com/fb/react/pull/9"
    upstream.create_pull.assert_not_called()
    existing.edit.assert_called_once_with(body="body")


def test_forked_pr_aborts_on_stale_base_content() -> None:
    """The upstream moved under the fix; opening it would revert their change."""
    fork = _rebase_repo(head_sha=None)
    upstream = MagicMock()
    upstream.get_branch.return_value.commit.sha = "base1"
    upstream.get_pulls.return_value = []
    stale = MagicMock()
    stale.decoded_content = b"changed upstream"
    upstream.get_contents.return_value = stale

    result = _deliver_forked(
        fork, upstream, expected_base_contents={"wf.yml": "original content"}
    )

    assert result.error_code == STALE_CONTENT_ERROR_CODE
    upstream.create_pull.assert_not_called()
    fork.create_git_commit.assert_not_called()
