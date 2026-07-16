import asyncio
from dataclasses import dataclass

from github import Auth, Github
from github.GithubException import GithubException
from github.PullRequest import PullRequest as GithubPullRequest
from github.Repository import Repository as GithubRepository

from app.core.config import settings
from app.services.github.app_client import GitHubAppClient

STALE_CONTENT_ERROR_CODE = "stale_fix_workflow_changed"
USER_COMMITS_ERROR_CODE = "user_commits_on_fix_branch"


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


def _is_bot_login(login: str | None, bot_login: str) -> bool:
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
        if not _is_bot_login(author_login, bot_login):
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
        file_sha: str | None = (
            existing.sha if not isinstance(existing, list) else existing[0].sha
        )
    except GithubException:
        file_sha = None

    if not new_content.endswith("\n"):
        new_content += "\n"
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
) -> str:
    if open_prs:
        pr = open_prs[0]
        pr.edit(body=pr_body)
        pr.create_issue_comment(_update_comment_body(updated_paths))
        return pr.html_url

    pr = repo.create_pull(
        title=pr_title,
        body=pr_body,
        head=fix_branch,
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
