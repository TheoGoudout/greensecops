from app.core.config import Settings

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
