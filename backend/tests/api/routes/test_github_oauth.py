"""Tests for the /api/v1/auth/github/ OAuth endpoints."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import User

CALLBACK_URL = f"{settings.API_V1_STR}/auth/github/callback"


def _post(client: TestClient, **form_fields) -> object:
    return client.post(CALLBACK_URL, data=form_fields)


# ─── /callback — config guard ─────────────────────────────────────────────────


def test_github_callback_oauth_not_configured_returns_503(client: TestClient) -> None:
    with (
        patch.object(settings, "GITHUB_CLIENT_ID", None),
        patch.object(settings, "GITHUB_CLIENT_SECRET", None),
    ):
        response = _post(client, code="somecode")

    assert response.status_code == 503
    assert response.json()["detail"] == "GitHub OAuth not configured"


def test_github_callback_missing_client_secret_returns_503(
    client: TestClient,
) -> None:
    with (
        patch.object(settings, "GITHUB_CLIENT_ID", "test-id"),
        patch.object(settings, "GITHUB_CLIENT_SECRET", None),
    ):
        response = _post(client, code="somecode", client_id="test-id")

    assert response.status_code == 503


# ─── /callback — client_id validation ────────────────────────────────────────


def test_github_callback_client_id_mismatch_returns_400(client: TestClient) -> None:
    with (
        patch.object(settings, "GITHUB_CLIENT_ID", "real-client-id"),
        patch.object(settings, "GITHUB_CLIENT_SECRET", "test-secret"),
    ):
        response = _post(client, code="somecode", client_id="wrong-client-id")

    assert response.status_code == 400
    assert response.json()["detail"] == "GitHub Client ID not matching"


# ─── /callback — OAuth exchange failure ──────────────────────────────────────


def test_github_callback_exchange_failure_returns_400(client: TestClient) -> None:
    mock_client = AsyncMock()
    mock_client.exchange_oauth_code.side_effect = Exception("bad_verification_code")

    from app.api.deps import get_github_app_client
    from app.main import app

    app.dependency_overrides[get_github_app_client] = lambda: mock_client

    try:
        with (
            patch.object(settings, "GITHUB_CLIENT_ID", "test-id"),
            patch.object(settings, "GITHUB_CLIENT_SECRET", "test-secret"),
        ):
            response = _post(client, code="bad-code", client_id="test-id")
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
            response = _post(client, code="valid-code", client_id="test-id")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "access_token" in response.json()

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
            response = _post(client, code="valid-code-2", client_id="test-id")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200

    user = db.exec(select(User).where(User.github_id == 987654321)).first()
    assert user is not None
    assert "noemailuser@users.noreply.github.com" in user.email


# ─── /callback — existing user update ────────────────────────────────────────


def test_github_callback_updates_existing_user_by_github_id(
    client: TestClient, db: Session
) -> None:
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
            response = _post(client, code="code-existing", client_id="test-id")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    db.refresh(existing)
    assert existing.github_username == "new-login"


def test_github_callback_updates_existing_user_by_email(
    client: TestClient, db: Session
) -> None:
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
            response = _post(client, code="code-email-match", client_id="test-id")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    db.refresh(existing)
    assert existing.github_id == 444555666
    assert existing.github_username == "email-match-user"


def test_github_callback_passes_code_verifier_to_exchange(
    client: TestClient,
) -> None:
    mock_client = AsyncMock()
    mock_client.exchange_oauth_code.return_value = "gho_pkce_token"
    mock_client.get_oauth_user.return_value = {
        "id": 777888999,
        "login": "pkceuser",
        "email": "pkce@example.com",
        "name": "PKCE User",
    }

    from app.api.deps import get_github_app_client
    from app.main import app

    app.dependency_overrides[get_github_app_client] = lambda: mock_client

    try:
        with (
            patch.object(settings, "GITHUB_CLIENT_ID", "test-id"),
            patch.object(settings, "GITHUB_CLIENT_SECRET", "test-secret"),
        ):
            response = _post(
                client,
                code="pkce-code",
                client_id="test-id",
                code_verifier="my-verifier-string",
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    mock_client.exchange_oauth_code.assert_called_once_with(
        "pkce-code",
        code_verifier="my-verifier-string",
        redirect_uri=settings.GITHUB_OAUTH_REDIRECT_URI,
    )
