import secrets
import warnings
from typing import Annotated, Any, Literal

from pydantic import (
    AnyUrl,
    BeforeValidator,
    EmailStr,
    HttpUrl,
    PostgresDsn,
    computed_field,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Use top level .env file (one level above ./backend/)
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    # Empty by default; resolved in _resolve_secret_key: a random key is generated
    # for local dev, but a value MUST be supplied in staging/production so that
    # JWTs stay valid across restarts and replicas.
    SECRET_KEY: str = ""
    # 60 minutes * 24 hours * 8 days = 8 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    FRONTEND_HOST: str = "http://localhost:5173"
    BACKEND_HOST: str = "http://localhost:8000"
    # Public-facing backend URL embedded in generated workflow files as default.
    # Set this to the canonical production URL so customer workflows point to prod
    # by default. vars.GREENSECOPS_URL in the customer repo overrides for dev/staging.
    GREENSECOPS_PUBLIC_URL: str = ""
    APP_URL: str = "https://greensecops.io"
    GITHUB_ACTION_REF: str = "greensecops/greensecops-action@v1"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        origins = [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_HOST
        ]
        if self.GITHUB_WEBHOOK_URL:
            origins.append(self.GITHUB_WEBHOOK_URL.rstrip("/"))
        return origins

    PROJECT_NAME: str
    SENTRY_DSN: HttpUrl | None = None
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    EMAIL_TEST_USER: EmailStr = "test@example.com"
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # GitHub App
    GITHUB_APP_ID: int | None = None
    GITHUB_APP_PRIVATE_KEY: str | None = None  # PEM content, not file path
    GITHUB_WEBHOOK_SECRET: str | None = None
    GITHUB_CLIENT_ID: str | None = None
    GITHUB_CLIENT_SECRET: str | None = None
    # Dev only: public tunnel base URL (e.g. ngrok) for webhook delivery to
    # localhost. When set, the tunnel origin is added to the allowed CORS origins.
    GITHUB_WEBHOOK_URL: str | None = None

    # Bot account credential for outreach PRs on *external* repos. The GitHub App
    # is not installed on arbitrary open-source projects, so those repos cannot
    # be delivered to with an installation token: we fork them into a dedicated
    # bot account and open a cross-repo PR. This is the bot user's user-to-server
    # OAuth token (the App acting on behalf of the bot user) — it can fork any
    # public repo and open cross-fork PRs, and inherits the App's Workflows:write
    # permission needed to push .github/workflows changes. GITHUB_BOT_LOGIN is
    # the fork owner login; when empty it is derived from the token and cached.
    GITHUB_BOT_TOKEN: str | None = None
    GITHUB_BOT_LOGIN: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def GITHUB_OAUTH_REDIRECT_URI(self) -> str:
        # Must match the GitHub OAuth App "Authorization callback URL".
        return f"{self.FRONTEND_HOST}/auth/github/callback"

    # LLM
    DEFAULT_LLM_PROVIDER: str = "openai"
    DEFAULT_LLM_MODEL: str = "gpt-4o-mini"
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    AI_PROVIDERS_CONFIG: str | None = None

    # LangSmith
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGCHAIN_API_KEY: str | None = None
    LANGCHAIN_PROJECT: str = "greensecops"

    # Stripe
    STRIPE_SECRET_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None
    STRIPE_PRICE_STARTER: str | None = None
    STRIPE_PRICE_PRO: str | None = None
    STRIPE_PRICE_ULTIMATE: str | None = None

    # OPA
    OPA_URL: str = "http://localhost:8181"

    # Docs
    DOCS_URL: str = "http://localhost:3002"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def WIKI_BASE_URL(self) -> str:
        return f"{self.DOCS_URL}/rules"

    # PR messaging
    GITHUB_BOT_HANDLE: str = "@greensecops"

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _resolve_secret_key(self) -> Self:
        if not self.SECRET_KEY:
            if self.ENVIRONMENT == "local":
                # Ephemeral key is acceptable for a single local dev process.
                self.SECRET_KEY = secrets.token_urlsafe(32)
            else:
                raise ValueError(
                    "SECRET_KEY must be set in staging/production. An unset key "
                    "would be randomly regenerated per process, invalidating all "
                    "JWTs across restarts and replicas."
                )
        return self

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )

        return self


settings = Settings()  # type: ignore
