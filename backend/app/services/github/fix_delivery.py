import asyncio
from dataclasses import dataclass

from github import Auth, Github
from github.GithubException import GithubException
from github.InputGitTreeElement import InputGitTreeElement
from github.PullRequest import PullRequest as GithubPullRequest
from github.Repository import Repository as GithubRepository

from app.core.config import settings
from app.services.github.app_client import GitHubAppClient

STALE_CONTENT_ERROR_CODE = "stale_fix_workflow_changed"
USER_COMMITS_ERROR_CODE = "user_commits_on_fix_branch"
# Every file the fix would write already says what the base branch says —
# there is no diff to open a PR for.
NOTHING_TO_DELIVER_ERROR_CODE = "nothing_to_deliver"


@dataclass
class FixDeliveryResult:
    pr_url: str | None = None
    comment_url: str | None = None
    error: str | None = None
    error_code: str | None = None


class _DeliveryAborted(Exception):
    """Internal: delivery aborted with a machine-readable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _normalize_bot_handle(handle: str | None) -> str:
    return (handle or "").lstrip("@").lower().removesuffix("[bot]")


def is_bot_login(login: str | None, bot_login: str) -> bool:
    """Whether a commit author login belongs to our GitHub App bot.

    ``bot_login`` is the authenticated App's own login (``<slug>[bot]``), which is
    how installation-token commits are attributed. The configured
    ``GITHUB_BOT_HANDLE`` is accepted too, so a cross-environment branch (e.g.
    touched by both the staging and production apps) still passes.
    """
    if not login:
        # Author unknown (e.g. commit without a linked account): stay
        # permissive so normal operation is not blocked.
        return True
    normalized = _normalize_bot_handle(login)
    return normalized in {
        _normalize_bot_handle(bot_login),
        _normalize_bot_handle(settings.GITHUB_BOT_HANDLE),
    }


def _fetch_file_content(repo: GithubRepository, file_path: str, ref: str) -> str | None:
    """Return the decoded content of a file at ref, or None if it is absent."""
    try:
        existing = repo.get_contents(file_path, ref=ref)
    except GithubException as exc:
        if exc.status == 404:
            return None
        raise
    if isinstance(existing, list):
        existing = existing[0]
    return existing.decoded_content.decode("utf-8", errors="replace")


def _check_base_content_fresh(
    repo: GithubRepository,
    file_path: str,
    base_branch: str,
    expected_base_content: str | None,
) -> None:
    """Abort delivery when the file changed on the base branch since analysis.

    Delivering would otherwise silently revert whatever the user changed after
    the fix was generated (the PR pushes the full patched file content).
    """
    if expected_base_content is None:
        return
    current = _fetch_file_content(repo, file_path, base_branch)
    if current is not None and current != expected_base_content:
        raise _DeliveryAborted(
            STALE_CONTENT_ERROR_CODE,
            f"{file_path} changed on {base_branch} since the fix was generated; "
            "re-analysis required",
        )


def _blob_modes(
    repo: GithubRepository, tree_sha: str, paths: set[str]
) -> dict[str, str]:
    """The file mode each of ``paths`` has in ``tree_sha``.

    Read rather than assumed, so rewriting a file cannot silently drop its
    executable bit. A path absent from the answer is one the tree does not have
    — a file this fix is adding — and the caller defaults it to ``100644``.
    """
    try:
        tree = repo.get_git_tree(tree_sha, recursive=True)
    except GithubException:
        return {}
    return {
        element.path: element.mode
        for element in tree.tree
        if element.path in paths and element.type == "blob"
    }


def _rebase_fix_branch(
    branch_repo: GithubRepository,
    base_repo: GithubRepository,
    fix_branch: str,
    base_sha: str,
    file_changes: list[tuple[str, str]],
    commit_messages: dict[str, str],
    override_user_commits: bool,
    bot_login: str,
) -> str | None:
    """Rebuild the fix branch as fresh commits on top of ``base_sha``.

    The branch used to be left alone whenever it backed an open PR, because
    force-pushing it *to* the base makes GitHub see zero commits ahead and
    auto-close the PR. Every redelivery therefore appended to whatever history
    the branch already had, on whatever base it was originally cut from: the PR
    drifted further behind the default branch with every run, and accumulated
    revert-and-re-fix commits that said nothing about the change.

    Building the new history first and moving the ref once avoids that
    entirely. The branch goes straight from its old tip to a tip that is
    already ahead of the current base, so it is never observed at zero commits
    ahead and the PR stays open and is updated in place.

    Rebuilding from the base tree each time is also what makes the branch
    self-reconciling: a file that drops out of the fix set simply carries base
    content again, and a file deleted on base is simply absent. Both used to
    need a forward-only reconciliation pass to undo.

    ``base_repo`` owns the base branch: the same repo as ``branch_repo`` for
    same-repo delivery, or the upstream for fork-based delivery, where the fix
    branch lives on the bot's fork. A fork shares the upstream's git objects,
    so the new commits parent onto the upstream base directly.

    Returns the new head SHA, or ``None`` when every file already matches base
    and there is nothing to commit.
    """
    try:
        branch_ref: object | None = branch_repo.get_git_ref(f"heads/{fix_branch}")
    except GithubException:
        branch_ref = None

    if branch_ref is not None and not override_user_commits:
        _refuse_to_overwrite_user_commits(
            branch_repo, branch_ref, fix_branch, bot_login
        )

    parent = branch_repo.get_git_commit(base_sha)
    modes = _blob_modes(base_repo, parent.tree.sha, {fp for fp, _ in file_changes})
    head_sha: str | None = None

    for file_path, new_content in file_changes:
        if not new_content.endswith("\n"):
            new_content += "\n"
        # Compared against the *base*, not against the branch: a fix that
        # reproduces what base already says adds nothing, and committing it
        # would put an empty commit in the PR on every redelivery.
        if _fetch_file_content(base_repo, file_path, base_sha) == new_content:
            continue
        tree = branch_repo.create_git_tree(
            [
                InputGitTreeElement(
                    path=file_path,
                    mode=modes.get(file_path, "100644"),
                    type="blob",
                    content=new_content,
                )
            ],
            base_tree=parent.tree,
        )
        parent = branch_repo.create_git_commit(
            commit_messages.get(file_path, f"chore: update {file_path}"),
            tree,
            [parent],
        )
        head_sha = parent.sha

    if head_sha is None:
        return None

    if branch_ref is None:
        branch_repo.create_git_ref(ref=f"refs/heads/{fix_branch}", sha=head_sha)
    else:
        branch_ref.edit(sha=head_sha, force=True)  # type: ignore[attr-defined]
    return head_sha


def _refuse_to_overwrite_user_commits(
    repo: GithubRepository,
    branch_ref: object,
    fix_branch: str,
    bot_login: str,
) -> None:
    """Abort if the branch's head commit was not written by the app bot.

    The rebase force-pushes, so anything a person pushed to the branch would be
    gone. This check used to run only on the paths that already force-pushed;
    now that every delivery does, it guards every delivery.
    """
    head = branch_ref.object.sha  # type: ignore[attr-defined]
    head_commit = repo.get_commit(head)
    author_login = head_commit.author.login if head_commit.author else None
    if not is_bot_login(author_login, bot_login):
        raise _DeliveryAborted(
            USER_COMMITS_ERROR_CODE,
            f"branch {fix_branch} has commits by {author_login}; "
            "not overwriting user work",
        )


def _update_comment_body(updated_paths: list[str]) -> str:
    if len(updated_paths) == 1:
        return f"{settings.PROJECT_NAME} re-analyzed and updated `{updated_paths[0]}`."
    paths_list = "\n".join(f"- `{p}`" for p in sorted(updated_paths))
    return f"{settings.PROJECT_NAME} re-analyzed and updated:\n\n{paths_list}"


def _update_or_create_open_pr(
    repo: GithubRepository,
    open_prs: list[GithubPullRequest],
    fix_branch: str,
    base_branch: str,
    pr_title: str,
    pr_body: str,
    updated_paths: list[str],
    head: str | None = None,
) -> str:
    """Update the open PR or create one on ``repo`` (the base repo).

    ``head`` defaults to ``fix_branch`` for same-repo delivery; cross-repo
    (fork) delivery passes ``<bot_login>:<fix_branch>`` so GitHub opens the PR
    from the fork's branch against the upstream base.
    """
    if open_prs:
        pr = open_prs[0]
        pr.edit(body=pr_body)
        pr.create_issue_comment(_update_comment_body(updated_paths))
        return pr.html_url

    pr = repo.create_pull(
        title=pr_title,
        body=pr_body,
        head=head or fix_branch,
        base=base_branch,
    )
    return pr.html_url


class FixDeliveryService:
    """Delivers LLM-generated fixes as PRs."""

    def __init__(self, app_client: GitHubAppClient) -> None:
        self._app = app_client

    async def update_or_create_workflow_action_pr(
        self,
        installation_id: int,
        full_name: str,
        base_branch: str,
        fix_branch: str,
        file_changes: list[tuple[str, str]],
        pr_title: str,
        pr_body: str,
        expected_base_contents: dict[str, str] | None = None,
        override_user_commits: bool = False,
        commit_messages: dict[str, str] | None = None,
    ) -> FixDeliveryResult:
        """Create or update a multi-file fix PR.

        If the branch already exists: reset it to the latest base SHA (rebase),
        apply the new file contents, then update the open PR body and post a
        comment. If no open PR exists, create one.

        Aborts (with a machine-readable ``error_code``) when a file changed
        on the base branch since the fix was generated, or when the fix branch
        carries user commits and ``override_user_commits`` is false.
        """
        try:
            token = await self._app.get_installation_token(installation_id)
            bot_login = await self._app.get_app_bot_login()

            def _upsert_batch_pr() -> str:
                repo = Github(auth=Auth.Token(token)).get_repo(full_name)
                base_sha = repo.get_branch(base_branch).commit.sha

                if expected_base_contents:
                    for fp, expected in expected_base_contents.items():
                        _check_base_content_fresh(repo, fp, base_branch, expected)
                # Fetched once, up front: both whether to reset the branch and
                # whether to update-vs-create the PR must agree on the same
                # open-PR snapshot, or the reset can auto-close the very PR
                # this was meant to update (see _prepare_fix_branch).
                open_prs = list(
                    repo.get_pulls(
                        state="open",
                        head=f"{repo.owner.login}:{fix_branch}",
                        base=base_branch,
                    )
                )
                head_sha = _rebase_fix_branch(
                    repo,
                    repo,
                    fix_branch,
                    base_sha,
                    file_changes,
                    {
                        fp: (commit_messages or {}).get(
                            fp, f"ci: add {settings.PROJECT_NAME} telemetry to {fp}"
                        )
                        for fp, _ in file_changes
                    },
                    override_user_commits,
                    bot_login,
                )
                if head_sha is None:
                    # Nothing this delivery changes is different from base. An
                    # open PR is left exactly as it is rather than reset to
                    # base, which would make GitHub close it as having nothing
                    # to merge.
                    if open_prs:
                        return str(open_prs[0].html_url)
                    raise _DeliveryAborted(
                        NOTHING_TO_DELIVER_ERROR_CODE,
                        "every file in this fix already matches the base branch",
                    )
                return _update_or_create_open_pr(
                    repo,
                    open_prs,
                    fix_branch,
                    base_branch,
                    pr_title,
                    pr_body,
                    updated_paths=[fp for fp, _ in file_changes],
                )

            return FixDeliveryResult(pr_url=await asyncio.to_thread(_upsert_batch_pr))
        except _DeliveryAborted as exc:
            return FixDeliveryResult(error=str(exc), error_code=exc.code)
        except Exception as exc:
            return FixDeliveryResult(error=str(exc))

    async def update_or_create_forked_pr(
        self,
        full_name: str,
        base_branch: str,
        fix_branch: str,
        file_changes: list[tuple[str, str]],
        pr_title: str,
        pr_body: str,
        expected_base_contents: dict[str, str] | None = None,
        override_user_commits: bool = False,
        commit_messages: dict[str, str] | None = None,
    ) -> FixDeliveryResult:
        """Create or update a cross-repo fix PR on an external repo.

        The GitHub App is not installed on ``full_name`` (an external
        open-source project), so a branch cannot be pushed to it directly.
        Instead the upstream is forked into the bot account, the fix branch is
        pushed to the fork, and a PR is opened from ``<bot_login>:<fix_branch>``
        against the upstream base branch.

        Mirrors :meth:`update_or_create_workflow_action_pr` and reuses the same
        helpers, but splits the work: the branch and file commits land on the
        fork, while the freshness check and the PR itself target the upstream.
        The fix branch is created at the upstream base SHA directly (forks share
        the upstream's git objects), so no separate fork-sync step is needed.
        """
        try:
            bot_login = await self._app.get_bot_login()

            def _upsert_forked_pr() -> str:
                bot = self._app.get_bot_github()
                upstream = bot.get_repo(full_name)
                fork = self._app.ensure_fork(bot, full_name)
                base_sha = upstream.get_branch(base_branch).commit.sha

                if expected_base_contents:
                    for fp, expected in expected_base_contents.items():
                        _check_base_content_fresh(upstream, fp, base_branch, expected)

                head = f"{bot_login}:{fix_branch}"
                # Fetched once, up front: the reset decision and the
                # update-vs-create decision must agree on the same open-PR
                # snapshot (see _prepare_fix_branch).
                open_prs = list(
                    upstream.get_pulls(
                        state="open",
                        head=head,
                        base=base_branch,
                    )
                )
                head_sha = _rebase_fix_branch(
                    fork,
                    upstream,
                    fix_branch,
                    base_sha,
                    file_changes,
                    {
                        fp: (commit_messages or {}).get(
                            fp, f"ci: add {settings.PROJECT_NAME} telemetry to {fp}"
                        )
                        for fp, _ in file_changes
                    },
                    override_user_commits,
                    bot_login,
                )
                if head_sha is None:
                    if open_prs:
                        return str(open_prs[0].html_url)
                    raise _DeliveryAborted(
                        NOTHING_TO_DELIVER_ERROR_CODE,
                        "every file in this fix already matches the base branch",
                    )
                return _update_or_create_open_pr(
                    upstream,
                    open_prs,
                    fix_branch,
                    base_branch,
                    pr_title,
                    pr_body,
                    updated_paths=[fp for fp, _ in file_changes],
                    head=head,
                )

            return FixDeliveryResult(pr_url=await asyncio.to_thread(_upsert_forked_pr))
        except _DeliveryAborted as exc:
            return FixDeliveryResult(error=str(exc), error_code=exc.code)
        except Exception as exc:
            return FixDeliveryResult(error=str(exc))

    async def post_fix_comment(
        self,
        installation_id: int,
        full_name: str,
        base_branch: str,
        body: str,
    ) -> FixDeliveryResult:
        """Deliver fixes as a commit comment on the base branch HEAD.

        The ``comment`` delivery mode surfaces the suggested changes inline on
        the latest commit instead of opening a PR, for repos that prefer review
        without a branch. Returns the created comment's URL.
        """
        try:
            token = await self._app.get_installation_token(installation_id)

            def _post() -> str:
                repo = Github(auth=Auth.Token(token)).get_repo(full_name)
                head_sha = repo.get_branch(base_branch).commit.sha
                comment = repo.get_commit(head_sha).create_comment(body)
                return comment.html_url

            return FixDeliveryResult(comment_url=await asyncio.to_thread(_post))
        except Exception as exc:
            return FixDeliveryResult(error=str(exc))
