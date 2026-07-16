"""Tests for GitHubAppClient repo/installation listing and OAuth exchange."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from github.GithubException import GithubException

from app.services.github.app_client import GitHubAppClient


class FakeResponse:
    def __init__(self, json_data: Any, status_code: int = 200) -> None:
        self._json = json_data
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if not self.is_success:
            raise RuntimeError(f"HTTP {self.status_code}")


def _fake_async_client(
    get_responses: list[FakeResponse] | None = None,
    post_response: FakeResponse | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Build a MagicMock that mimics `httpx.AsyncClient()` as a context manager."""
    client = MagicMock()
    if get_responses is not None:
        client.get = AsyncMock(side_effect=get_responses)
    if post_response is not None:
        client.post = AsyncMock(return_value=post_response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock(return_value=ctx)
    return factory, client


@pytest.fixture()
def app_client() -> GitHubAppClient:
    return GitHubAppClient(redis_client=AsyncMock())


# ─── list_installation_repositories ──────────────────────────────────────────


def _make_repo(repo_id: int, full_name: str, default_branch: str | None) -> MagicMock:
    repo = MagicMock()
    repo.id = repo_id
    repo.full_name = full_name
    repo.default_branch = default_branch
    return repo


def _mock_integration(repos: list[MagicMock]) -> MagicMock:
    mock_installation = MagicMock()
    mock_installation.get_repos.return_value = repos
    mock_integration = MagicMock()
    mock_integration.get_app_installation.return_value = mock_installation
    return mock_integration


def test_list_installation_repositories_paginates(
    app_client: GitHubAppClient,
) -> None:
    repos = [_make_repo(i, f"o/r{i}", "main") for i in range(100)] + [
        _make_repo(i, f"o/r{i}", "dev") for i in range(100, 150)
    ]

    with patch.object(
        app_client, "_get_integration", return_value=_mock_integration(repos)
    ):
        result = asyncio.run(app_client.list_installation_repositories(123))

    assert len(result) == 150
    assert result[0].github_repo_id == 0
    assert result[-1].full_name == "o/r149"
    assert result[-1].default_branch == "dev"


def test_list_installation_repositories_default_branch_fallback(
    app_client: GitHubAppClient,
) -> None:
    repos = [_make_repo(7, "o/r", None)]

    with patch.object(
        app_client, "_get_integration", return_value=_mock_integration(repos)
    ):
        result = asyncio.run(app_client.list_installation_repositories(1))

    assert result[0].default_branch == "main"


def test_list_installation_repositories_empty(
    app_client: GitHubAppClient,
) -> None:
    with patch.object(
        app_client, "_get_integration", return_value=_mock_integration([])
    ):
        result = asyncio.run(app_client.list_installation_repositories(1))

    assert result == []


# ─── get_app_bot_login ───────────────────────────────────────────────────────


def _mock_app_integration(slug: str | None) -> MagicMock:
    mock_app = MagicMock()
    mock_app.slug = slug
    mock_integration = MagicMock()
    mock_integration.get_app.return_value = mock_app
    return mock_integration


def test_get_app_bot_login_derives_from_slug() -> None:
    redis = AsyncMock()
    redis.get.return_value = None
    client = GitHubAppClient(redis_client=redis)

    with patch.object(
        client,
        "_get_integration",
        return_value=_mock_app_integration("greensecops-staging"),
    ):
        login = asyncio.run(client.get_app_bot_login())

    assert login == "greensecops-staging[bot]"
    redis.setex.assert_awaited_once()


def test_get_app_bot_login_uses_cache() -> None:
    redis = AsyncMock()
    redis.get.return_value = b"greensecops-staging[bot]"
    client = GitHubAppClient(redis_client=redis)

    with patch.object(client, "_get_integration") as get_integration:
        login = asyncio.run(client.get_app_bot_login())

    assert login == "greensecops-staging[bot]"
    get_integration.assert_not_called()
    redis.setex.assert_not_awaited()


def test_get_app_bot_login_falls_back_on_error() -> None:
    redis = AsyncMock()
    redis.get.return_value = None
    client = GitHubAppClient(redis_client=redis)

    integration = MagicMock()
    integration.get_app.side_effect = GithubException(500, {}, None)
    with patch.object(client, "_get_integration", return_value=integration):
        login = asyncio.run(client.get_app_bot_login())

    from app.core.config import settings

    assert login == settings.GITHUB_BOT_HANDLE
    redis.setex.assert_not_awaited()


# ─── list_user_installations ─────────────────────────────────────────────────


def _make_user_installation(
    inst_id: int, account_id: int, login: str, acc_type: str
) -> MagicMock:
    account = MagicMock()
    account.id = account_id
    account.login = login
    account.type = acc_type
    inst = MagicMock()
    inst.id = inst_id
    inst.account = account
    return inst


def test_list_user_installations_maps_accounts(
    app_client: GitHubAppClient,
) -> None:
    installations = [
        _make_user_installation(100, 1, "alice", "User"),
        _make_user_installation(200, 2, "acme", "Organization"),
    ]
    mock_user = MagicMock()
    mock_user.get_installations.return_value = installations
    mock_gh = MagicMock()
    mock_gh.get_user.return_value = mock_user

    with patch("app.services.github.app_client.Github", return_value=mock_gh):
        installs = asyncio.run(app_client.list_user_installations("user-token"))

    assert len(installs) == 2
    assert installs[0].installation_id == 100
    assert installs[0].account_login == "alice"
    assert installs[0].account_type == "User"
    assert installs[1].account_id == 2
    assert installs[1].account_type == "Organization"


def test_list_user_installations_empty(app_client: GitHubAppClient) -> None:
    mock_user = MagicMock()
    mock_user.get_installations.return_value = []
    mock_gh = MagicMock()
    mock_gh.get_user.return_value = mock_user

    with patch("app.services.github.app_client.Github", return_value=mock_gh):
        installs = asyncio.run(app_client.list_user_installations("user-token"))

    assert installs == []


# ─── exchange_oauth_code ─────────────────────────────────────────────────────


def _mock_oauth_application(token: str = "gho_x") -> tuple[MagicMock, MagicMock]:
    """Return (patchable Github class mock, oauth application mock)."""
    oauth_app = MagicMock()
    oauth_app.get_access_token.return_value = MagicMock(token=token)
    gh = MagicMock()
    gh.get_oauth_application.return_value = oauth_app
    return MagicMock(return_value=gh), oauth_app


def test_exchange_oauth_code_returns_token(app_client: GitHubAppClient) -> None:
    github_cls, oauth_app = _mock_oauth_application("gho_x")

    with patch("app.services.github.app_client.Github", github_cls):
        token = asyncio.run(app_client.exchange_oauth_code("the-code"))

    assert token == "gho_x"
    oauth_app.get_access_token.assert_called_once_with("the-code", None)


def test_exchange_oauth_code_passes_code_verifier(
    app_client: GitHubAppClient,
) -> None:
    github_cls, oauth_app = _mock_oauth_application("gho_y")

    with patch("app.services.github.app_client.Github", github_cls):
        token = asyncio.run(
            app_client.exchange_oauth_code("the-code", code_verifier="ver1fier")
        )

    assert token == "gho_y"
    oauth_app.get_access_token.assert_called_once_with("the-code", "ver1fier")


def test_exchange_oauth_code_raises_on_error(
    app_client: GitHubAppClient,
) -> None:
    github_cls, oauth_app = _mock_oauth_application()
    oauth_app.get_access_token.side_effect = GithubException(
        400, {"error": "bad_verification_code"}, None
    )

    with patch("app.services.github.app_client.Github", github_cls):
        with pytest.raises(GithubException):
            asyncio.run(app_client.exchange_oauth_code("bad"))


# ─── get_bot_login ───────────────────────────────────────────────────────────


def test_get_bot_login_uses_configured_login() -> None:
    from app.core.config import settings

    redis = AsyncMock()
    client = GitHubAppClient(redis_client=redis)

    with patch.object(settings, "GITHUB_BOT_LOGIN", "greensecops-bot"):
        login = asyncio.run(client.get_bot_login())

    assert login == "greensecops-bot"
    redis.get.assert_not_awaited()


def test_get_bot_login_derives_and_caches() -> None:
    from app.core.config import settings

    redis = AsyncMock()
    redis.get.return_value = None
    client = GitHubAppClient(redis_client=redis)

    mock_user = MagicMock(login="greensecops-bot")
    mock_gh = MagicMock()
    mock_gh.get_user.return_value = mock_user

    with (
        patch.object(settings, "GITHUB_BOT_LOGIN", None),
        patch.object(settings, "GITHUB_BOT_TOKEN", "bot-tok"),
        patch("app.services.github.app_client.Github", return_value=mock_gh),
    ):
        login = asyncio.run(client.get_bot_login())

    assert login == "greensecops-bot"
    redis.setex.assert_awaited_once()


# ─── ensure_fork ─────────────────────────────────────────────────────────────


def test_ensure_fork_reuses_existing_fork() -> None:
    client = GitHubAppClient(redis_client=AsyncMock())
    parent = MagicMock()
    parent.full_name = "facebook/react"
    # ``parent`` is a reserved MagicMock constructor kwarg, so set it as an
    # attribute after construction.
    existing = MagicMock(fork=True)
    existing.parent = parent
    bot_user = MagicMock(login="greensecops-bot")
    bot_user.get_repo.return_value = existing
    bot = MagicMock()
    bot.get_user.return_value = bot_user

    result = client.ensure_fork(bot, "facebook/react")

    assert result is existing
    bot_user.get_repo.assert_called_once_with("react")
    # No fork is created and the upstream is not fetched when a fork already exists.
    bot.get_repo.assert_not_called()


def test_ensure_fork_creates_when_missing() -> None:
    client = GitHubAppClient(redis_client=AsyncMock())
    bot_user = MagicMock(login="greensecops-bot")
    bot_user.get_repo.side_effect = GithubException(404, {}, None)
    fork = MagicMock(default_branch="main")
    fork.get_branch.return_value = MagicMock()  # ready immediately
    upstream = MagicMock()
    upstream.create_fork.return_value = fork
    bot = MagicMock()
    bot.get_user.return_value = bot_user
    bot.get_repo.return_value = upstream

    result = client.ensure_fork(bot, "facebook/react")

    assert result is fork
    bot.get_repo.assert_called_once_with("facebook/react")
    upstream.create_fork.assert_called_once()
