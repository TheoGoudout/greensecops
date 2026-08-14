import pytest

from app.core.config import LOCAL_FRONTEND_HOST, Settings

REQUIRED = {
    "PROJECT_NAME": "Test",
    "POSTGRES_SERVER": "localhost",
    "POSTGRES_USER": "postgres",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "testpassword",
}


def _settings(**overrides: str) -> Settings:
    return Settings(_env_file=None, **REQUIRED, **overrides)  # type: ignore[call-arg]


def test_all_cors_origins_includes_frontend_host() -> None:
    settings = _settings(
        FRONTEND_HOST="http://localhost:5173",
        BACKEND_CORS_ORIGINS="http://localhost,https://example.com/",
    )
    assert settings.all_cors_origins == [
        "http://localhost",
        "https://example.com",
        "http://localhost:5173",
    ]


def test_all_cors_origins_includes_public_url_when_set() -> None:
    settings = _settings(GREENSECOPS_PUBLIC_URL="https://example.ngrok.io/")
    assert "https://example.ngrok.io" in settings.all_cors_origins


def test_all_cors_origins_omits_public_url_when_unset() -> None:
    settings = _settings()
    assert settings.GREENSECOPS_PUBLIC_URL == ""
    assert all("ngrok" not in origin for origin in settings.all_cors_origins)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_default_frontend_host_is_rejected_when_deployed(environment: str) -> None:
    """The localhost default is a bug outside local, not a fallback.

    It is also what an *empty* FRONTEND_HOST resolves to, since env_ignore_empty
    is on — which is how a deployment ends up with a localhost-only CORS origin
    and a localhost OAuth callback while looking healthy from the server side.
    """
    with pytest.raises(ValueError, match="FRONTEND_HOST"):
        _settings(ENVIRONMENT=environment, SECRET_KEY="a-real-key")


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_public_frontend_host_is_accepted_when_deployed(environment: str) -> None:
    settings = _settings(
        ENVIRONMENT=environment,
        SECRET_KEY="a-real-key",
        FRONTEND_HOST="https://app.staging.greensecops.com",
    )
    assert settings.all_cors_origins == ["https://app.staging.greensecops.com"]
    assert (
        settings.GITHUB_OAUTH_REDIRECT_URI
        == "https://app.staging.greensecops.com/auth/github/callback"
    )


def test_default_frontend_host_is_fine_locally() -> None:
    settings = _settings()
    assert settings.ENVIRONMENT == "local"
    assert settings.FRONTEND_HOST == LOCAL_FRONTEND_HOST
