"""Tests for GitHubAppClient repo/installation listing and OAuth exchange."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


def test_exchange_oauth_code_omits_redirect_uri_by_default(
    app_client: GitHubAppClient,
) -> None:
    resp = FakeResponse({"access_token": "gho_x"})
    factory, client = _fake_async_client(post_response=resp)

    with patch("app.services.github.app_client.httpx.AsyncClient", factory):
        token = asyncio.run(app_client.exchange_oauth_code("the-code"))

    assert token == "gho_x"
    sent_body = client.post.call_args.kwargs["json"]
    assert "redirect_uri" not in sent_body
    assert sent_body["code"] == "the-code"


def test_exchange_oauth_code_includes_redirect_uri_when_given(
    app_client: GitHubAppClient,
) -> None:
    resp = FakeResponse({"access_token": "gho_y"})
    factory, client = _fake_async_client(post_response=resp)

    with patch("app.services.github.app_client.httpx.AsyncClient", factory):
        token = asyncio.run(
            app_client.exchange_oauth_code(
                "the-code", redirect_uri="https://example.com/cb"
            )
        )

    assert token == "gho_y"
    sent_body = client.post.call_args.kwargs["json"]
    assert sent_body["redirect_uri"] == "https://example.com/cb"


def test_exchange_oauth_code_raises_on_error(
    app_client: GitHubAppClient,
) -> None:
    resp = FakeResponse(
        {"error": "bad_verification_code", "error_description": "expired"}
    )
    factory, _ = _fake_async_client(post_response=resp)

    with patch("app.services.github.app_client.httpx.AsyncClient", factory):
        with pytest.raises(ValueError, match="GitHub OAuth error"):
            asyncio.run(app_client.exchange_oauth_code("bad"))
