import asyncio
from dataclasses import dataclass

from github import Auth, Github
from github.GithubException import GithubException

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

                encoded = new_content.encode("utf-8")
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
