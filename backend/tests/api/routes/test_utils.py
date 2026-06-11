"""Tests for /api/v1/utils/ endpoints."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import settings


def test_health_check(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_STR}/utils/health-check/")
    assert response.status_code == 200
    assert response.json() is True


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
