import base64
import hashlib
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
import redis.asyncio as aioredis
from github import Auth, Github

from app.core.config import settings


@dataclass
class WorkflowFileContent:
    path: str
    content: str
    content_hash: str
    sha: str


class GitHubAppClient:
    """GitHub App client with JWT auth and cached installation tokens."""

    _GITHUB_API = "https://api.github.com"
    _TOKEN_TTL = 55 * 60  # 55 minutes (tokens last 60 min)

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    def _build_jwt(self) -> str:
        now = int(time.time())
        payload = {
            "iat": now - 60,  # issued 60s ago to account for clock skew
            "exp": now + 540,  # 9 minutes from now
            "iss": str(settings.GITHUB_APP_ID),
        }
        private_key = self._decode_private_key()
        return jwt.encode(payload, private_key, algorithm="RS256")

    def _decode_private_key(self) -> str:
        key = settings.GITHUB_APP_PRIVATE_KEY or ""
        # Support base64-encoded keys (useful for env vars without newline issues)
        if not key.startswith("-----"):
            try:
                key = base64.b64decode(key).decode()
            except Exception:
                pass
        return key

    async def get_installation_token(self, installation_id: int) -> str:
        cache_key = f"gh:install_token:{installation_id}"
        cached = await self._redis.get(cache_key)
        if cached:
            return cached.decode()

        token = await self._exchange_installation_token(installation_id)
        await self._redis.setex(cache_key, self._TOKEN_TTL, token)
        return token

    async def _exchange_installation_token(self, installation_id: int) -> str:
        jwt_token = self._build_jwt()
        url = f"{self._GITHUB_API}/app/installations/{installation_id}/access_tokens"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response.raise_for_status()
            return str(response.json()["token"])

    def get_installation_github(self, token: str) -> Github:
        return Github(auth=Auth.Token(token))

    async def fetch_workflow_files(
        self, installation_id: int, full_name: str
    ) -> list[WorkflowFileContent]:
        token = await self.get_installation_token(installation_id)
        owner, repo = full_name.split("/", 1)
        url = f"{self._GITHUB_API}/repos/{owner}/{repo}/contents/.github/workflows"

        async with httpx.AsyncClient() as client:
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            response = await client.get(url, headers=headers)
            if response.status_code == 404:
                return []
            response.raise_for_status()
            entries: list[dict[str, Any]] = response.json()

        workflow_files: list[WorkflowFileContent] = []
        for entry in entries:
            if entry.get("type") != "file":
                continue
            name = entry.get("name", "")
            if not (name.endswith(".yml") or name.endswith(".yaml")):
                continue
            content = await self._fetch_file_content(token, entry["url"])
            if content is not None:
                content_hash = hashlib.sha256(content.encode()).hexdigest()
                workflow_files.append(
                    WorkflowFileContent(
                        path=entry["path"],
                        content=content,
                        content_hash=content_hash,
                        sha=entry.get("sha", ""),
                    )
                )
        return workflow_files

    async def _fetch_file_content(self, token: str, url: str) -> str | None:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            if not response.is_success:
                return None
            data = response.json()
            if data.get("encoding") == "base64":
                raw = base64.b64decode(data["content"].replace("\n", ""))
                return raw.decode("utf-8", errors="replace")
            return str(data.get("content", ""))

    async def get_app_installation(self, installation_id: int) -> dict[str, Any]:
        jwt_token = self._build_jwt()
        url = f"{self._GITHUB_API}/app/installations/{installation_id}"
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response.raise_for_status()
            return dict(response.json())

    async def get_oauth_user(self, access_token: str) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._GITHUB_API}/user",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            response.raise_for_status()
            return dict(response.json())

    async def exchange_oauth_code(self, code: str) -> str:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://github.com/login/oauth/access_token",
                json={
                    "client_id": settings.GITHUB_CLIENT_ID,
                    "client_secret": settings.GITHUB_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": settings.GITHUB_OAUTH_REDIRECT_URI,
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                raise ValueError(f"GitHub OAuth error: {data['error_description']}")
            return str(data["access_token"])
