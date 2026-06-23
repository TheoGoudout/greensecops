import asyncio
import base64
import hashlib
from dataclasses import dataclass
from typing import Any

import httpx
import redis.asyncio as aioredis
from github import Auth, Github, GithubIntegration
from github.GithubException import GithubException

from app.core.config import settings


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

    async def fetch_workflow_files(
        self, installation_id: int | None, full_name: str
    ) -> list[WorkflowFileContent]:
        if installation_id is not None:
            token: str | None = await self.get_installation_token(installation_id)
        else:
            token = None

        def _fetch() -> list[WorkflowFileContent]:
            gh = Github(auth=Auth.Token(token)) if token is not None else Github()
            repo = gh.get_repo(full_name)
            try:
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
        self, code: str, redirect_uri: str | None = None
    ) -> str:
        # PyGitHub does not support OAuth code exchange — raw HTTP required
        body: dict[str, Any] = {
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "code": code,
        }
        if redirect_uri is not None:
            body["redirect_uri"] = redirect_uri
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://github.com/login/oauth/access_token",
                json=body,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                raise ValueError(f"GitHub OAuth error: {data['error_description']}")
            return str(data["access_token"])
