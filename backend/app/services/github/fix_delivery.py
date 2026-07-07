import asyncio
from dataclasses import dataclass

from github import Auth, Github
from github.GithubException import GithubException
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


def _is_bot_login(login: str | None) -> bool:
    """Whether a commit author login belongs to our GitHub App bot."""
    if not login:
        # Author unknown (e.g. commit without a linked account): stay
        # permissive so normal operation is not blocked.
        return True
    return _normalize_bot_handle(login) == _normalize_bot_handle(
        settings.GITHUB_BOT_HANDLE
    )


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
) -> bool:
    """Create the fix branch, or reset an existing one to the base SHA.

    Refuses to force-reset a branch whose head commit was not authored by the
    app bot (the user pushed their own commits) unless explicitly overridden.
    Returns whether the branch already existed.
    """
    try:
        branch_ref = repo.get_git_ref(f"heads/{fix_branch}")
    except GithubException:
        repo.create_git_ref(ref=f"refs/heads/{fix_branch}", sha=base_sha)
        return False

    if not override_user_commits and branch_ref.object.sha != base_sha:
        head_commit = repo.get_commit(branch_ref.object.sha)
        author_login = head_commit.author.login if head_commit.author else None
        if not _is_bot_login(author_login):
            raise _DeliveryAborted(
                USER_COMMITS_ERROR_CODE,
                f"branch {fix_branch} has commits by {author_login}; "
                "not overwriting user work",
            )
    branch_ref.edit(sha=base_sha, force=True)
    return True


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


def _update_or_create_open_pr(
    repo: GithubRepository,
    branch_existed: bool,
    fix_branch: str,
    base_branch: str,
    pr_title: str,
    pr_body: str,
) -> str:
    if branch_existed:
        open_prs = list(
            repo.get_pulls(
                state="open",
                head=f"{repo.owner.login}:{fix_branch}",
                base=base_branch,
            )
        )
        if open_prs:
            pr = open_prs[0]
            pr.edit(body=pr_body)
            pr.create_issue_comment(
                f"{settings.PROJECT_NAME} re-analyzed this workflow. "
                "Fixes have been updated."
            )
            return pr.html_url

    pr = repo.create_pull(
        title=pr_title,
        body=pr_body,
        head=fix_branch,
        base=base_branch,
    )
    return pr.html_url


class FixDeliveryService:
    """Delivers LLM-generated fixes as PRs or issue comments."""

    def __init__(self, app_client: GitHubAppClient) -> None:
        self._app = app_client

    async def update_or_create_pr(
        self,
        installation_id: int,
        full_name: str,
        base_branch: str,
        fix_branch: str,
        file_path: str,
        new_content: str,
        pr_title: str,
        pr_body: str,
        expected_base_content: str | None = None,
        override_user_commits: bool = False,
    ) -> FixDeliveryResult:
        """Create or update a single-file fix PR.

        If the branch already exists: reset it to the latest base SHA (rebase),
        apply the new file content, then update the open PR body and post a
        comment. If no open PR exists, create one.

        Aborts (with a machine-readable ``error_code``) when the file changed
        on the base branch since the fix was generated, or when the fix branch
        carries user commits and ``override_user_commits`` is false.
        """
        try:
            token = await self._app.get_installation_token(installation_id)

            def _upsert_pr() -> str:
                repo = Github(auth=Auth.Token(token)).get_repo(full_name)
                base_sha = repo.get_branch(base_branch).commit.sha

                _check_base_content_fresh(
                    repo, file_path, base_branch, expected_base_content
                )
                branch_existed = _prepare_fix_branch(
                    repo, fix_branch, base_sha, override_user_commits
                )
                _upsert_file(
                    repo, file_path, new_content, fix_branch, f"fix(ci): {pr_title}"
                )
                return _update_or_create_open_pr(
                    repo, branch_existed, fix_branch, base_branch, pr_title, pr_body
                )

            return FixDeliveryResult(pr_url=await asyncio.to_thread(_upsert_pr))
        except _DeliveryAborted as exc:
            return FixDeliveryResult(error=str(exc), error_code=exc.code)
        except Exception as exc:
            return FixDeliveryResult(error=str(exc))

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
    ) -> FixDeliveryResult:
        """Create or update a multi-file fix PR.

        Same rebase-and-update semantics as update_or_create_pr but for
        multiple file changes in one branch update.
        """
        try:
            token = await self._app.get_installation_token(installation_id)

            def _upsert_batch_pr() -> str:
                repo = Github(auth=Auth.Token(token)).get_repo(full_name)
                base_sha = repo.get_branch(base_branch).commit.sha

                if expected_base_contents:
                    for fp, expected in expected_base_contents.items():
                        _check_base_content_fresh(repo, fp, base_branch, expected)
                branch_existed = _prepare_fix_branch(
                    repo, fix_branch, base_sha, override_user_commits
                )
                for fp, new_content in file_changes:
                    _upsert_file(
                        repo,
                        fp,
                        new_content,
                        fix_branch,
                        f"ci: add {settings.PROJECT_NAME} telemetry to {fp}",
                    )
                return _update_or_create_open_pr(
                    repo, branch_existed, fix_branch, base_branch, pr_title, pr_body
                )

            return FixDeliveryResult(pr_url=await asyncio.to_thread(_upsert_batch_pr))
        except _DeliveryAborted as exc:
            return FixDeliveryResult(error=str(exc), error_code=exc.code)
        except Exception as exc:
            return FixDeliveryResult(error=str(exc))

    async def deliver_as_comment(
        self,
        installation_id: int,
        full_name: str,
        body: str,
        issue_title: str | None = None,
    ) -> FixDeliveryResult:
        """Post the fix as a comment on a dedicated, findable issue.

        Finds an open issue with ``issue_title`` (creating it when absent)
        instead of assuming issue #1 exists and is ours.
        """
        title = issue_title or f"{settings.PROJECT_NAME} fixes"
        try:
            token = await self._app.get_installation_token(installation_id)

            def _post_comment() -> str:
                repo = Github(auth=Auth.Token(token)).get_repo(full_name)
                target = None
                for issue in repo.get_issues(state="open")[:100]:
                    if issue.title == title and issue.pull_request is None:
                        target = issue
                        break
                if target is None:
                    target = repo.create_issue(
                        title=title,
                        body=(
                            f"{settings.PROJECT_NAME} posts suggested workflow "
                            "fixes on this issue."
                        ),
                    )
                comment = target.create_comment(body)
                return comment.html_url

            return FixDeliveryResult(comment_url=await asyncio.to_thread(_post_comment))
        except Exception as exc:
            return FixDeliveryResult(error=str(exc))
