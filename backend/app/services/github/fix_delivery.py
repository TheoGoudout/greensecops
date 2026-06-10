import base64
from dataclasses import dataclass

import httpx

from app.services.github.app_client import GitHubAppClient


@dataclass
class FixDeliveryResult:
    pr_url: str | None = None
    comment_url: str | None = None
    error: str | None = None


class FixDeliveryService:
    """Delivers LLM-generated fixes as PRs or review comments."""

    _GITHUB_API = "https://api.github.com"

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
            owner, repo = full_name.split("/", 1)
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }

            async with httpx.AsyncClient() as client:
                # Get base branch SHA
                ref_resp = await client.get(
                    f"{self._GITHUB_API}/repos/{owner}/{repo}/git/ref/heads/{base_branch}",
                    headers=headers,
                )
                ref_resp.raise_for_status()
                base_sha = ref_resp.json()["object"]["sha"]

                # Create fix branch
                await client.post(
                    f"{self._GITHUB_API}/repos/{owner}/{repo}/git/refs",
                    headers=headers,
                    json={"ref": f"refs/heads/{fix_branch}", "sha": base_sha},
                )

                # Get current file SHA (needed for update)
                file_resp = await client.get(
                    f"{self._GITHUB_API}/repos/{owner}/{repo}/contents/{file_path}",
                    headers=headers,
                    params={"ref": fix_branch},
                )
                file_sha = (
                    file_resp.json().get("sha", "") if file_resp.is_success else ""
                )

                # Commit updated file
                await client.put(
                    f"{self._GITHUB_API}/repos/{owner}/{repo}/contents/{file_path}",
                    headers=headers,
                    json={
                        "message": f"fix(ci): {pr_title}",
                        "content": base64.b64encode(new_content.encode()).decode(),
                        "branch": fix_branch,
                        **({"sha": file_sha} if file_sha else {}),
                    },
                )

                # Open PR
                pr_resp = await client.post(
                    f"{self._GITHUB_API}/repos/{owner}/{repo}/pulls",
                    headers=headers,
                    json={
                        "title": pr_title,
                        "body": pr_body,
                        "head": fix_branch,
                        "base": base_branch,
                    },
                )
                pr_resp.raise_for_status()
                return FixDeliveryResult(pr_url=pr_resp.json()["html_url"])

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
            owner, repo = full_name.split("/", 1)
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json={"body": body},
                )
                response.raise_for_status()
                return FixDeliveryResult(comment_url=response.json()["html_url"])
        except Exception as exc:
            return FixDeliveryResult(error=str(exc))
