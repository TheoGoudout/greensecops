import asyncio
import base64
import hashlib
import re
from dataclasses import dataclass
from typing import Any

import redis.asyncio as aioredis
from github import Auth, Github, GithubIntegration
from github.GithubException import GithubException

from app.core.config import settings
from app.models.enums import PullRequestState

_PR_URL_RE = re.compile(
    r"https://github\.com/(?P<full_name>[^/]+/[^/]+)/pull/(?P<number>\d+)"
)


def parse_pr_url(pr_url: str) -> tuple[str, int] | None:
    m = _PR_URL_RE.match(pr_url)
    if m:
        return m.group("full_name"), int(m.group("number"))
    return None


@dataclass
class WorkflowFileContent:
    path: str
    content: str
    content_hash: str
    sha: str


@dataclass
class InstallationRepo:
    github_repo_id: int
    full_name: str
    default_branch: str


@dataclass
class UserInstallation:
    installation_id: int
    account_id: int
    account_login: str
    account_type: str  # "User" | "Organization"


class GitHubAppClient:
    """GitHub App client with PyGitHub and Redis-cached installation tokens."""

    _TOKEN_TTL = 55 * 60  # 55 minutes (tokens last 60 min)

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    def _decode_private_key(self) -> str:
        key = settings.GITHUB_APP_PRIVATE_KEY or ""
        key = key.strip()
        # Support base64-encoded keys (useful for env vars without newline issues)
        if not key.startswith("-----"):
            try:
                key = base64.b64decode(key).decode()
            except Exception:
                pass
        return key

    def _get_integration(self) -> GithubIntegration:
        return GithubIntegration(
            auth=Auth.AppAuth(settings.GITHUB_APP_ID, self._decode_private_key())
        )

    async def get_installation_token(self, installation_id: int) -> str:
        cache_key = f"gh:install_token:{installation_id}"
        cached = await self._redis.get(cache_key)
        if cached:
            return cached.decode()

        def _exchange() -> str:
            return self._get_integration().get_access_token(installation_id).token

        token = await asyncio.to_thread(_exchange)
        await self._redis.setex(cache_key, self._TOKEN_TTL, token)
        return token

    def get_installation_github(self, token: str) -> Github:
        return Github(auth=Auth.Token(token))

    async def get_pr_state(
        self, installation_id: int, full_name: str, pr_number: int
    ) -> PullRequestState:
        token = await self.get_installation_token(installation_id)

        def _fetch() -> PullRequestState:
            repo = Github(auth=Auth.Token(token)).get_repo(full_name)
            pr = repo.get_pull(pr_number)
            if pr.merged:
                return PullRequestState.merged
            return PullRequestState(pr.state)

        return await asyncio.to_thread(_fetch)

    async def fetch_workflow_files(
        self, installation_id: int | None, full_name: str, ref: str | None = None
    ) -> list[WorkflowFileContent]:
        """Fetch workflow files at ``ref`` (branch or commit SHA).

        When ``ref`` is empty the repository's default branch is used, so an
        analysis triggered for a feature branch sees that branch's content.
        """
        if installation_id is not None:
            token: str | None = await self.get_installation_token(installation_id)
        else:
            token = None

        def _fetch() -> list[WorkflowFileContent]:
            gh = Github(auth=Auth.Token(token)) if token is not None else Github()
            repo = gh.get_repo(full_name)
            try:
                if ref:
                    contents = repo.get_contents(".github/workflows", ref=ref)
                else:
                    contents = repo.get_contents(".github/workflows")
            except GithubException as exc:
                if exc.status == 404:
                    return []
                raise
            if not isinstance(contents, list):
                contents = [contents]
            results = []
            for cf in contents:
                if not (cf.name.endswith(".yml") or cf.name.endswith(".yaml")):
                    continue
                decoded = cf.decoded_content.decode("utf-8", errors="replace")
                results.append(
                    WorkflowFileContent(
                        path=cf.path,
                        content=decoded,
                        content_hash=hashlib.sha256(decoded.encode()).hexdigest(),
                        sha=cf.sha,
                    )
                )
            return results

        return await asyncio.to_thread(_fetch)

    async def fetch_public_repo_info(self, full_name: str) -> InstallationRepo:
        """Fetch repo metadata via unauthenticated PyGitHub (public repos only)."""
        from github.GithubException import UnknownObjectException

        def _fetch() -> InstallationRepo:
            repo = Github().get_repo(full_name)
            return InstallationRepo(
                github_repo_id=repo.id,
                full_name=repo.full_name,
                default_branch=repo.default_branch or "main",
            )

        try:
            return await asyncio.to_thread(_fetch)
        except UnknownObjectException:
            raise ValueError(f"Repository '{full_name}' not found or is private")

    async def list_installation_repositories(
        self, installation_id: int
    ) -> list[InstallationRepo]:
        def _list() -> list[InstallationRepo]:
            installation = self._get_integration().get_app_installation(installation_id)
            return [
                InstallationRepo(
                    github_repo_id=repo.id,
                    full_name=repo.full_name,
                    default_branch=repo.default_branch or "main",
                )
                for repo in installation.get_repos()
            ]

        return await asyncio.to_thread(_list)

    async def list_user_installations(
        self, user_access_token: str
    ) -> list[UserInstallation]:
        def _list() -> list[UserInstallation]:
            user = Github(auth=Auth.Token(user_access_token)).get_user()
            results = []
            for inst in user.get_installations():
                account = inst.account
                results.append(
                    UserInstallation(
                        installation_id=inst.id,
                        account_id=account.id,
                        account_login=account.login,
                        account_type=account.type,
                    )
                )
            return results

        return await asyncio.to_thread(_list)

    async def get_app_installation(self, installation_id: int) -> dict[str, Any]:
        def _get() -> dict[str, Any]:
            return (
                self._get_integration().get_app_installation(installation_id).raw_data
            )  # type: ignore[return-value]

        return await asyncio.to_thread(_get)

    async def get_oauth_user(self, access_token: str) -> dict[str, Any]:
        def _get() -> dict[str, Any]:
            user = Github(auth=Auth.Token(access_token)).get_user()
            return {
                "id": user.id,
                "login": user.login,
                "name": user.name,
                "email": user.email,
                "avatar_url": user.avatar_url,
            }

        return await asyncio.to_thread(_get)

    async def exchange_oauth_code(
        self,
        code: str,
        code_verifier: str | None = None,
        redirect_uri: str | None = None,  # noqa: ARG002
    ) -> str:
        def _exchange() -> str:
            app = Github().get_oauth_application(
                settings.GITHUB_CLIENT_ID,
                settings.GITHUB_CLIENT_SECRET,
            )
            token = app.get_access_token(code, code_verifier)
            return token.token

        return await asyncio.to_thread(_exchange)
