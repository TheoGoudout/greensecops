import asyncio
import base64
import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any

import redis.asyncio as aioredis
from github import Auth, Github, GithubIntegration
from github.GithubException import GithubException
from github.Repository import Repository as GithubRepository

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
    _APP_LOGIN_TTL = 24 * 60 * 60  # 24 hours (the app slug is stable)
    # Forks are created asynchronously; poll until the fork's git data is ready.
    _FORK_POLL_ATTEMPTS = 30
    _FORK_POLL_INTERVAL = 2  # seconds (≈60s max)

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

    async def get_app_bot_login(self) -> str:
        """Return the authenticated App's own bot login (``<slug>[bot]``).

        Commits made with an installation token are authored by this login, so it
        is the identity to trust when deciding whether a branch carries only the
        bot's own work. Deriving it from the App itself (rather than a separately
        configured handle) keeps the check correct across environments whose app
        slugs differ, e.g. ``greensecops`` vs ``greensecops-staging``.

        The slug is stable, so the result is cached in Redis. Falls back to
        ``settings.GITHUB_BOT_HANDLE`` if the lookup fails, so behavior is never
        worse than the previous config-only comparison.
        """
        cache_key = "gh:app_bot_login"
        cached = await self._redis.get(cache_key)
        if cached:
            return str(cached.decode())

        def _fetch_slug() -> str | None:
            slug: str | None = self._get_integration().get_app().slug
            return slug

        try:
            slug = await asyncio.to_thread(_fetch_slug)
        except Exception:
            slug = None

        bot_login = f"{slug}[bot]" if slug else settings.GITHUB_BOT_HANDLE
        if slug:
            await self._redis.setex(cache_key, self._APP_LOGIN_TTL, bot_login)
        return bot_login

    def get_installation_github(self, token: str) -> Github:
        return Github(auth=Auth.Token(token))

    # ─── Bot account (external outreach PRs) ─────────────────────────────────

    def get_bot_github(self) -> Github:
        """Return a PyGitHub client authenticated as the outreach bot account.

        Raises if ``GITHUB_BOT_TOKEN`` is unset, so callers can surface a clear
        "no bot credential" state instead of an opaque auth failure.
        """
        if not settings.GITHUB_BOT_TOKEN:
            raise RuntimeError("GITHUB_BOT_TOKEN is not configured")
        return Github(auth=Auth.Token(settings.GITHUB_BOT_TOKEN))

    async def get_bot_login(self) -> str:
        """Return the bot account login (the owner of outreach forks).

        Uses ``GITHUB_BOT_LOGIN`` when set, otherwise derives it from the token
        and caches it in Redis (the login is stable).
        """
        if settings.GITHUB_BOT_LOGIN:
            return settings.GITHUB_BOT_LOGIN
        cache_key = "gh:bot_login"
        cached = await self._redis.get(cache_key)
        if cached:
            return str(cached.decode())

        def _fetch_login() -> str:
            return self.get_bot_github().get_user().login

        login = await asyncio.to_thread(_fetch_login)
        await self._redis.setex(cache_key, self._APP_LOGIN_TTL, login)
        return login

    def ensure_fork(self, bot: Github, full_name: str) -> GithubRepository:
        """Return the bot's fork of ``full_name``, creating it if needed.

        Forks are created asynchronously by GitHub, so after creating one this
        polls until its default branch resolves before returning it.
        """
        _, repo_name = full_name.split("/", 1)
        bot_user = bot.get_user()
        try:
            existing = bot_user.get_repo(repo_name)
            if (
                existing.fork
                and existing.parent
                and existing.parent.full_name.lower() == full_name.lower()
            ):
                return existing
        except GithubException:
            pass

        fork = bot.get_repo(full_name).create_fork()
        for _ in range(self._FORK_POLL_ATTEMPTS):
            try:
                fork.get_branch(fork.default_branch)
                return fork
            except GithubException:
                time.sleep(self._FORK_POLL_INTERVAL)
                fork = bot.get_repo(f"{bot_user.login}/{repo_name}")
        return fork

    async def get_pr_state_with_token(
        self, token: str, full_name: str, pr_number: int
    ) -> PullRequestState:
        def _fetch() -> PullRequestState:
            repo = Github(auth=Auth.Token(token)).get_repo(full_name)
            pr = repo.get_pull(pr_number)
            if pr.merged:
                return PullRequestState.merged
            return PullRequestState(pr.state)

        return await asyncio.to_thread(_fetch)

    async def get_pr_state(
        self, installation_id: int, full_name: str, pr_number: int
    ) -> PullRequestState:
        token = await self.get_installation_token(installation_id)
        return await self.get_pr_state_with_token(token, full_name, pr_number)

    async def get_pr_mergeable_state(
        self, installation_id: int, full_name: str, pr_number: int
    ) -> str | None:
        """Return GitHub's mergeable_state (e.g. ``clean``, ``dirty``) for a PR.

        GitHub sends no webhook when a base-branch push makes a PR conflicted,
        so this is polled on demand. ``None`` when GitHub hasn't computed it.
        """
        token = await self.get_installation_token(installation_id)

        def _fetch() -> str | None:
            repo = Github(auth=Auth.Token(token)).get_repo(full_name)
            return repo.get_pull(pr_number).mergeable_state

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
