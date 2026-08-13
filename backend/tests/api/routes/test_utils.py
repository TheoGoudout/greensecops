"""Tests for /api/v1/utils/ endpoints."""

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.__version__ import __version__
from app.core.config import settings


def test_health_check(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_STR}/utils/health-check/")
    assert response.status_code == 200
    assert response.json() is True


def test_health_check_returns_a_bare_boolean(client: TestClient) -> None:
    """The container HEALTHCHECK and deploy-reusable.yml's smoke test both
    depend on this shape, so widening it into an object is a breaking change
    dressed up as an improvement. /utils/version/ exists so nobody needs to."""
    response = client.get(f"{settings.API_V1_STR}/utils/health-check/")
    assert isinstance(response.json(), bool)


def test_version_is_public(client: TestClient) -> None:
    """No credentials: the dashboard footer reads this before anyone signs in."""
    response = client.get(f"{settings.API_V1_STR}/utils/version/")
    assert response.status_code == 200

    body = response.json()
    assert body["version"] == __version__
    assert body["environment"] == settings.ENVIRONMENT


def test_version_matches_the_root_version_file() -> None:
    """The API must report the same version the dashboard was built with.

    scripts/validate_versions.py enforces this across the whole repository;
    asserting it here too means a stale __version__.py fails the backend suite
    rather than only the pre-commit hook, which is the faster signal.
    """
    # backend/tests/api/routes/ -> repository root is four levels up.
    version_file = Path(__file__).resolve().parents[4] / "VERSION"
    assert version_file.read_text(encoding="utf-8").strip() == __version__


def test_test_email_sends(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    with patch("app.api.routes.utils.send_email") as mock_send:
        response = client.post(
            f"{settings.API_V1_STR}/utils/test-email/",
            params={"email_to": "test@example.com"},
            headers=superuser_token_headers,
        )
    assert response.status_code == 201
    mock_send.assert_called_once()
