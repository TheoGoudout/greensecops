"""Tests for the /api/v1/auth/github/ OAuth endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import User

LOGIN_URL = f"{settings.API_V1_STR}/auth/github/login"
CALLBACK_URL = f"{settings.API_V1_STR}/auth/github/callback"


@pytest.fixture(autouse=True)
def _isolate_oauth_cookies(client: TestClient):
    """Each OAuth attempt is an independent browser session.

    The module-scoped client otherwise persists the gh_oauth_state cookie set by
    the /login redirect into later popup-flow callback tests (which legitimately
    carry no such cookie in production).
    """
    client.cookies.clear()
    yield
    client.cookies.clear()


# ─── /login ──────────────────────────────────────────────────────────────────


def test_github_login_oauth_not_configured_returns_503(client: TestClient) -> None:
    # Arrange — no client_id
    with patch.object(settings, "GITHUB_CLIENT_ID", None):
        response = client.get(LOGIN_URL, follow_redirects=False)

    # Assert
    assert response.status_code == 503
    assert response.json()["detail"] == "GitHub OAuth not configured"


def test_github_login_redirects_to_github(client: TestClient) -> None:
    with patch.object(settings, "GITHUB_CLIENT_ID", "test-client-id"):
        response = client.get(LOGIN_URL, follow_redirects=False)

    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert "github.com/login/oauth/authorize" in location
    assert "client_id=test-client-id" in location
    assert "scope=read%3Auser%2Cuser%3Aemail" in location or "scope=read" in location


# ─── /callback — config guard ─────────────────────────────────────────────────


def test_github_callback_oauth_not_configured_returns_503(client: TestClient) -> None:
    with (
        patch.object(settings, "GITHUB_CLIENT_ID", None),
        patch.object(settings, "GITHUB_CLIENT_SECRET", None),
    ):
        response = client.get(CALLBACK_URL, params={"code": "somecode"})

    assert response.status_code == 503
    assert response.json()["detail"] == "GitHub OAuth not configured"


def test_github_callback_missing_client_secret_returns_503(
    client: TestClient,
) -> None:
    with (
        patch.object(settings, "GITHUB_CLIENT_ID", "test-id"),
        patch.object(settings, "GITHUB_CLIENT_SECRET", None),
    ):
        response = client.get(CALLBACK_URL, params={"code": "somecode"})

    assert response.status_code == 503


# ─── /callback — CSRF state validation (server-initiated flow) ───────────────


def test_github_callback_state_mismatch_returns_400(client: TestClient) -> None:
    # A state cookie present but not matching the returned state → rejected.
    client.cookies.set("gh_oauth_state", "the-real-state")
    with (
        patch.object(settings, "GITHUB_CLIENT_ID", "test-id"),
        patch.object(settings, "GITHUB_CLIENT_SECRET", "test-secret"),
    ):
        response = client.get(
            CALLBACK_URL,
            params={"code": "somecode", "state": "attacker-state"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid OAuth state"


def test_github_login_sets_state_cookie(client: TestClient) -> None:
    with patch.object(settings, "GITHUB_CLIENT_ID", "test-client-id"):
        response = client.get(LOGIN_URL, follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "gh_oauth_state" in response.cookies


# ─── /callback — OAuth exchange failure ──────────────────────────────────────


def test_github_callback_exchange_failure_returns_400(client: TestClient) -> None:
    mock_client = AsyncMock()
    mock_client.exchange_oauth_code.side_effect = Exception("bad_verification_code")

    with (
        patch.object(settings, "GITHUB_CLIENT_ID", "test-id"),
        patch.object(settings, "GITHUB_CLIENT_SECRET", "test-secret"),
        patch("app.api.deps.get_github_app_client", return_value=mock_client),
        patch("app.api.routes.github_oauth.GitHubAppClientDep", mock_client),
    ):
        from app.api.deps import get_github_app_client
        from app.main import app

        app.dependency_overrides[get_github_app_client] = lambda: mock_client

        try:
            response = client.get(CALLBACK_URL, params={"code": "bad-code"})
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "GitHub OAuth failed" in response.json()["detail"]


# ─── /callback — new user creation ───────────────────────────────────────────


def test_github_callback_creates_new_user(client: TestClient, db: Session) -> None:
    mock_client = AsyncMock()
    mock_client.exchange_oauth_code.return_value = "gho_fake_token"
    mock_client.get_oauth_user.return_value = {
        "id": 123456789,
        "login": "testghuser",
        "email": "testghuser@example.com",
        "name": "Test GH User",
    }

    from app.api.deps import get_github_app_client
    from app.main import app

    app.dependency_overrides[get_github_app_client] = lambda: mock_client

    try:
        with (
            patch.object(settings, "GITHUB_CLIENT_ID", "test-id"),
            patch.object(settings, "GITHUB_CLIENT_SECRET", "test-secret"),
        ):
            response = client.get(CALLBACK_URL, params={"code": "valid-code"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data

    # Verify user was created in DB
    from sqlmodel import select

    user = db.exec(select(User).where(User.github_id == 123456789)).first()
    assert user is not None
    assert user.github_username == "testghuser"


def test_github_callback_creates_new_user_no_email_uses_noreply(
    client: TestClient, db: Session
) -> None:
    mock_client = AsyncMock()
    mock_client.exchange_oauth_code.return_value = "gho_fake_token2"
    mock_client.get_oauth_user.return_value = {
        "id": 987654321,
        "login": "noemailuser",
        "email": None,
        "name": None,
    }

    from app.api.deps import get_github_app_client
    from app.main import app

    app.dependency_overrides[get_github_app_client] = lambda: mock_client

    try:
        with (
            patch.object(settings, "GITHUB_CLIENT_ID", "test-id"),
            patch.object(settings, "GITHUB_CLIENT_SECRET", "test-secret"),
        ):
            response = client.get(CALLBACK_URL, params={"code": "valid-code-2"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data

    from sqlmodel import select

    user = db.exec(select(User).where(User.github_id == 987654321)).first()
    assert user is not None
    assert "noemailuser@users.noreply.github.com" in user.email


# ─── /callback — existing user update ────────────────────────────────────────


def test_github_callback_updates_existing_user_by_github_id(
    client: TestClient, db: Session
) -> None:
    # Arrange — create user with a known github_id
    existing = User(
        email="existing-gh@example.com",
        hashed_password="$argon2id$fake",
        github_id=111222333,
        github_username="old-login",
        is_active=True,
    )
    db.add(existing)
    db.commit()
    db.refresh(existing)

    mock_client = AsyncMock()
    mock_client.exchange_oauth_code.return_value = "gho_token_existing"
    mock_client.get_oauth_user.return_value = {
        "id": 111222333,
        "login": "new-login",
        "email": "existing-gh@example.com",
        "name": "Existing User",
    }

    from app.api.deps import get_github_app_client
    from app.main import app

    app.dependency_overrides[get_github_app_client] = lambda: mock_client

    try:
        with (
            patch.object(settings, "GITHUB_CLIENT_ID", "test-id"),
            patch.object(settings, "GITHUB_CLIENT_SECRET", "test-secret"),
        ):
            response = client.get(CALLBACK_URL, params={"code": "code-existing"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    db.refresh(existing)
    assert existing.github_username == "new-login"


def test_github_callback_updates_existing_user_by_email(
    client: TestClient, db: Session
) -> None:
    # Arrange — user exists with matching email but no github_id yet
    email = "email-match@example.com"
    existing = User(
        email=email,
        hashed_password="$argon2id$fake",
        github_id=None,
        github_username=None,
        is_active=True,
    )
    db.add(existing)
    db.commit()
    db.refresh(existing)

    mock_client = AsyncMock()
    mock_client.exchange_oauth_code.return_value = "gho_token_email_match"
    mock_client.get_oauth_user.return_value = {
        "id": 444555666,
        "login": "email-match-user",
        "email": email,
        "name": "Email Match User",
    }

    from app.api.deps import get_github_app_client
    from app.main import app

    app.dependency_overrides[get_github_app_client] = lambda: mock_client

    try:
        with (
            patch.object(settings, "GITHUB_CLIENT_ID", "test-id"),
            patch.object(settings, "GITHUB_CLIENT_SECRET", "test-secret"),
        ):
            response = client.get(CALLBACK_URL, params={"code": "code-email-match"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    db.refresh(existing)
    assert existing.github_id == 444555666
    assert existing.github_username == "email-match-user"
