import asyncio
from dataclasses import dataclass

from github import Auth, Github
from github.ContentFile import ContentFile
from github.GithubException import GithubException
from github.PullRequest import PullRequest as GithubPullRequest
from github.Repository import Repository as GithubRepository

from app.core.config import settings
from app.services.github.app_client import GitHubAppClient

STALE_CONTENT_ERROR_CODE = "stale_fix_workflow_changed"
USER_COMMITS_ERROR_CODE = "user_commits_on_fix_branch"

WORKFLOW_DIR = ".github/workflows"


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


def _prepare_fix_branch(
    repo: GithubRepository,
    fix_branch: str,
    base_sha: str,
    override_user_commits: bool,
    bot_login: str,
    reset_to_base: bool,
) -> None:
    """Create the fix branch, or reset an existing one to the base SHA.

    ``reset_to_base`` must be false when the branch already backs an open PR:
    force-pushing an open PR's head to be even with its base makes GitHub
    auto-close the PR (zero commits ahead to merge) before the new fix
    commits land, which silently replaces the PR with a new one instead of
    updating it. The reset is only safe for a branch with no open PR to lose.

    Refuses to force-reset a branch whose head commit was not authored by the
    app bot (the user pushed their own commits) unless explicitly overridden.
    """
    try:
        branch_ref = repo.get_git_ref(f"heads/{fix_branch}")
    except GithubException:
        repo.create_git_ref(ref=f"refs/heads/{fix_branch}", sha=base_sha)
        return

    if not reset_to_base:
        return

    if not override_user_commits and branch_ref.object.sha != base_sha:
        head_commit = repo.get_commit(branch_ref.object.sha)
        author_login = head_commit.author.login if head_commit.author else None
        if not is_bot_login(author_login, bot_login):
            raise _DeliveryAborted(
                USER_COMMITS_ERROR_CODE,
                f"branch {fix_branch} has commits by {author_login}; "
                "not overwriting user work",
            )
    branch_ref.edit(sha=base_sha, force=True)


def _upsert_file(
    repo: GithubRepository,
    file_path: str,
    new_content: str,
    branch: str,
    commit_message: str,
) -> None:
    try:
        existing = repo.get_contents(file_path, ref=branch)
        if isinstance(existing, list):
            existing = existing[0]
        file_sha: str | None = existing.sha
        existing_content: str | None = existing.decoded_content.decode(
            "utf-8", errors="replace"
        )
    except GithubException:
        file_sha = None
        existing_content = None

    if not new_content.endswith("\n"):
        new_content += "\n"
    # The branch already carries this exact content (e.g. an unchanged fix
    # re-included in the delivery set): committing it again would only add an
    # empty, churny commit to the PR. Nothing to do.
    if existing_content is not None and existing_content == new_content:
        return
    encoded = new_content.encode("utf-8")
    if file_sha:
        repo.update_file(
            path=file_path,
            message=commit_message,
            content=encoded,
            sha=file_sha,
            branch=branch,
        )
    else:
        repo.create_file(
            path=file_path,
            message=commit_message,
            content=encoded,
            branch=branch,
        )


def _list_workflow_files(repo: GithubRepository, ref: str) -> list[ContentFile]:
    """Return the *.yml/*.yaml content files under .github/workflows at ref.

    Yields an empty list when the directory is absent (404), mirroring
    ``app_client.fetch_workflow_files``.
    """
    try:
        contents = repo.get_contents(WORKFLOW_DIR, ref=ref)
    except GithubException as exc:
        if exc.status == 404:
            return []
        raise
    if not isinstance(contents, list):
        contents = [contents]
    return [cf for cf in contents if cf.name.endswith((".yml", ".yaml"))]


def _remove_outdated_workflow_files(
    branch_repo: GithubRepository,
    base_repo: GithubRepository,
    fix_branch: str,
    base_branch: str,
    keep_paths: set[str],
) -> list[str]:
    """Reconcile the fix branch so it modifies exactly ``keep_paths``.

    Updating an open PR does not reset the fix branch to base (that would
    auto-close the PR — see ``_prepare_fix_branch``), so a workflow file the
    branch changed in an earlier run lingers on the branch even after it drops
    out of the current fix set (its issues were resolved, or it was deleted on
    base). Left alone it keeps showing a stale change in the PR — or, for a file
    deleted on base, a modify/delete conflict that makes the PR unmergeable.

    ``keep_paths`` is the set of workflow paths delivered this run; every one of
    them is (re)written by the caller, so they are never touched here. For each
    other ``*.yml``/``*.yaml`` file on the fix branch we compare it to base and
    apply a forward-only commit (no history rewrite):

    * absent on base → ``delete_file`` (deleted on base after the branch was cut);
    * present on base but the branch content differs → an earlier fix we applied
      that is no longer needed: revert it to the base content so it drops out of
      the PR diff;
    * identical to base → an untouched user workflow file inherited from base:
      leave it alone (we never delete files the user owns).

    ``base_repo`` owns the base branch — the same repo as ``branch_repo`` for
    same-repo delivery, or the upstream for fork-based delivery. Returns the
    paths that were removed or reverted.
    """
    base_paths = {cf.path for cf in _list_workflow_files(base_repo, base_branch)}
    reconciled: list[str] = []
    for cf in _list_workflow_files(branch_repo, fix_branch):
        if cf.path in keep_paths:
            continue
        if cf.path not in base_paths:
            branch_repo.delete_file(
                path=cf.path,
                message=f"chore: remove {cf.path} deleted from {base_branch}",
                sha=cf.sha,
                branch=fix_branch,
            )
            reconciled.append(cf.path)
            continue
        base_content = _fetch_file_content(base_repo, cf.path, base_branch)
        branch_content = _fetch_file_content(branch_repo, cf.path, fix_branch)
        if base_content is None or branch_content == base_content:
            # Untouched user file (branch matches base): leave it in place.
            continue
        _upsert_file(
            branch_repo,
            cf.path,
            base_content,
            fix_branch,
            f"chore: revert {cf.path} no longer part of the fix set",
        )
        reconciled.append(cf.path)
    return reconciled


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
                _prepare_fix_branch(
                    repo,
                    fix_branch,
                    base_sha,
                    override_user_commits,
                    bot_login,
                    reset_to_base=not open_prs,
                )
                if open_prs:
                    _remove_outdated_workflow_files(
                        repo,
                        repo,
                        fix_branch,
                        base_branch,
                        keep_paths={fp for fp, _ in file_changes},
                    )
                for fp, new_content in file_changes:
                    _upsert_file(
                        repo,
                        fp,
                        new_content,
                        fix_branch,
                        (commit_messages or {}).get(
                            fp, f"ci: add {settings.PROJECT_NAME} telemetry to {fp}"
                        ),
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
                _prepare_fix_branch(
                    fork,
                    fix_branch,
                    base_sha,
                    override_user_commits,
                    bot_login,
                    reset_to_base=not open_prs,
                )
                if open_prs:
                    _remove_outdated_workflow_files(
                        fork,
                        upstream,
                        fix_branch,
                        base_branch,
                        keep_paths={fp for fp, _ in file_changes},
                    )
                for fp, new_content in file_changes:
                    _upsert_file(
                        fork,
                        fp,
                        new_content,
                        fix_branch,
                        (commit_messages or {}).get(
                            fp, f"ci: add {settings.PROJECT_NAME} telemetry to {fp}"
                        ),
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
