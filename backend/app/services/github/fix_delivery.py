import asyncio
from dataclasses import dataclass

from github import Auth, Github
from github.GithubException import GithubException

from app.core.config import settings
from app.services.github.app_client import GitHubAppClient


@dataclass
class FixDeliveryResult:
    pr_url: str | None = None
    comment_url: str | None = None
    error: str | None = None


class FixDeliveryService:
    """Delivers LLM-generated fixes as PRs or review comments."""

    def __init__(self, app_client: GitHubAppClient) -> None:
        self._app = app_client

    async def deliver_as_pr(
        self,
        installation_id: int,
        full_name: str,
        base_branch: str,
        fix_branch: str,
        file_path: str,
        new_content: str,
        pr_title: str,
        pr_body: str,
    ) -> FixDeliveryResult:
        try:
            token = await self._app.get_installation_token(installation_id)

            def _create_pr() -> str:
                repo = Github(auth=Auth.Token(token)).get_repo(full_name)
                base_sha = repo.get_branch(base_branch).commit.sha

                try:
                    repo.create_git_ref(ref=f"refs/heads/{fix_branch}", sha=base_sha)
                except GithubException:
                    pass  # branch already exists

                try:
                    existing = repo.get_contents(file_path, ref=fix_branch)
                    file_sha: str | None = (
                        existing.sha
                        if not isinstance(existing, list)
                        else existing[0].sha
                    )
                except GithubException:
                    file_sha = None

                content = (
                    new_content if new_content.endswith("\n") else new_content + "\n"
                )
                encoded = content.encode("utf-8")
                if file_sha:
                    repo.update_file(
                        path=file_path,
                        message=f"fix(ci): {pr_title}",
                        content=encoded,
                        sha=file_sha,
                        branch=fix_branch,
                    )
                else:
                    repo.create_file(
                        path=file_path,
                        message=f"fix(ci): {pr_title}",
                        content=encoded,
                        branch=fix_branch,
                    )

                pr = repo.create_pull(
                    title=pr_title,
                    body=pr_body,
                    head=fix_branch,
                    base=base_branch,
                )
                return pr.html_url

            return FixDeliveryResult(pr_url=await asyncio.to_thread(_create_pr))
        except Exception as exc:
            return FixDeliveryResult(error=str(exc))

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
    ) -> FixDeliveryResult:
        """Create or update a single-file fix PR.

        If the branch already exists: reset it to the latest base SHA (rebase),
        apply the new file content, then update the open PR body and post a
        comment. If no open PR exists, create one.
        """
        try:
            token = await self._app.get_installation_token(installation_id)

            def _upsert_pr() -> str:
                repo = Github(auth=Auth.Token(token)).get_repo(full_name)
                base_sha = repo.get_branch(base_branch).commit.sha
                content = (
                    new_content if new_content.endswith("\n") else new_content + "\n"
                )
                encoded = content.encode("utf-8")

                branch_exists = True
                try:
                    branch_ref = repo.get_git_ref(f"heads/{fix_branch}")
                    branch_ref.edit(sha=base_sha, force=True)
                except GithubException:
                    branch_exists = False
                    repo.create_git_ref(ref=f"refs/heads/{fix_branch}", sha=base_sha)

                try:
                    existing = repo.get_contents(file_path, ref=fix_branch)
                    file_sha: str | None = (
                        existing.sha
                        if not isinstance(existing, list)
                        else existing[0].sha
                    )
                except GithubException:
                    file_sha = None

                if file_sha:
                    repo.update_file(
                        path=file_path,
                        message=f"fix(ci): {pr_title}",
                        content=encoded,
                        sha=file_sha,
                        branch=fix_branch,
                    )
                else:
                    repo.create_file(
                        path=file_path,
                        message=f"fix(ci): {pr_title}",
                        content=encoded,
                        branch=fix_branch,
                    )

                if branch_exists:
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
                            f"{settings.PROJECT_NAME} re-analyzed this workflow. Fixes have been updated."
                        )
                        return pr.html_url

                pr = repo.create_pull(
                    title=pr_title,
                    body=pr_body,
                    head=fix_branch,
                    base=base_branch,
                )
                return pr.html_url

            return FixDeliveryResult(pr_url=await asyncio.to_thread(_upsert_pr))
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
    ) -> FixDeliveryResult:
        """Create or update a multi-file fix PR.

        Same rebase-and-update semantics as update_or_create_pr but for
        multiple file changes in one commit.
        """
        try:
            token = await self._app.get_installation_token(installation_id)

            def _upsert_batch_pr() -> str:
                repo = Github(auth=Auth.Token(token)).get_repo(full_name)
                base_sha = repo.get_branch(base_branch).commit.sha

                branch_exists = True
                try:
                    branch_ref = repo.get_git_ref(f"heads/{fix_branch}")
                    branch_ref.edit(sha=base_sha, force=True)
                except GithubException:
                    branch_exists = False
                    repo.create_git_ref(ref=f"refs/heads/{fix_branch}", sha=base_sha)

                for fp, new_content in file_changes:
                    if not new_content.endswith("\n"):
                        new_content += "\n"
                    encoded = new_content.encode("utf-8")
                    try:
                        existing = repo.get_contents(fp, ref=fix_branch)
                        file_sha: str | None = (
                            existing.sha
                            if not isinstance(existing, list)
                            else existing[0].sha
                        )
                    except GithubException:
                        file_sha = None

                    if file_sha:
                        repo.update_file(
                            path=fp,
                            message=f"ci: add {settings.PROJECT_NAME} telemetry to {fp}",
                            content=encoded,
                            sha=file_sha,
                            branch=fix_branch,
                        )
                    else:
                        repo.create_file(
                            path=fp,
                            message=f"ci: add {settings.PROJECT_NAME} telemetry to {fp}",
                            content=encoded,
                            branch=fix_branch,
                        )

                if branch_exists:
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
                            f"{settings.PROJECT_NAME} re-analyzed this workflow. Fixes have been updated."
                        )
                        return pr.html_url

                pr = repo.create_pull(
                    title=pr_title,
                    body=pr_body,
                    head=fix_branch,
                    base=base_branch,
                )
                return pr.html_url

            return FixDeliveryResult(pr_url=await asyncio.to_thread(_upsert_batch_pr))
        except Exception as exc:
            return FixDeliveryResult(error=str(exc))

    async def deliver_workflow_action_pr(
        self,
        installation_id: int,
        full_name: str,
        base_branch: str,
        fix_branch: str,
        file_changes: list[tuple[str, str]],
        pr_title: str,
        pr_body: str,
    ) -> FixDeliveryResult:
        try:
            token = await self._app.get_installation_token(installation_id)

            def _create_pr() -> str:
                repo = Github(auth=Auth.Token(token)).get_repo(full_name)
                base_sha = repo.get_branch(base_branch).commit.sha

                try:
                    repo.create_git_ref(ref=f"refs/heads/{fix_branch}", sha=base_sha)
                except GithubException:
                    pass  # branch already exists

                for file_path, new_content in file_changes:
                    try:
                        existing = repo.get_contents(file_path, ref=fix_branch)
                        file_sha: str | None = (
                            existing.sha
                            if not isinstance(existing, list)
                            else existing[0].sha
                        )
                    except GithubException:
                        file_sha = None

                    if not new_content.endswith("\n"):
                        new_content += "\n"
                    encoded = new_content.encode("utf-8")
                    if file_sha:
                        repo.update_file(
                            path=file_path,
                            message=f"ci: add {settings.PROJECT_NAME} telemetry to {file_path}",
                            content=encoded,
                            sha=file_sha,
                            branch=fix_branch,
                        )
                    else:
                        repo.create_file(
                            path=file_path,
                            message=f"ci: add {settings.PROJECT_NAME} telemetry to {file_path}",
                            content=encoded,
                            branch=fix_branch,
                        )

                pr = repo.create_pull(
                    title=pr_title,
                    body=pr_body,
                    head=fix_branch,
                    base=base_branch,
                )
                return pr.html_url

            return FixDeliveryResult(pr_url=await asyncio.to_thread(_create_pr))
        except Exception as exc:
            return FixDeliveryResult(error=str(exc))

    async def deliver_as_comment(
        self,
        installation_id: int,
        full_name: str,
        issue_number: int,
        body: str,
    ) -> FixDeliveryResult:
        try:
            token = await self._app.get_installation_token(installation_id)

            def _post_comment() -> str:
                repo = Github(auth=Auth.Token(token)).get_repo(full_name)
                comment = repo.get_issue(issue_number).create_comment(body)
                return comment.html_url

            return FixDeliveryResult(comment_url=await asyncio.to_thread(_post_comment))
        except Exception as exc:
            return FixDeliveryResult(error=str(exc))
