import logging

import sentry_sdk
from fastapi import FastAPI
from fastapi.routing import APIRoute
from slowapi.errors import RateLimitExceeded
from starlette.middleware.cors import CORSMiddleware

from app.__version__ import __version__
from app.api.main import api_router
from app.core.config import settings
from app.core.rate_limit import limiter, rate_limit_exceeded_handler

logger = logging.getLogger(__name__)


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=__version__,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    swagger_ui_init_oauth={
        "clientId": settings.GITHUB_CLIENT_ID,
        "usePkceWithAuthorizationCodeGrant": True,
    },
)

# Set all CORS enabled origins.
# A wildcard origin combined with credentials is unsafe (and rejected by
# browsers), so disable credentials when "*" is present rather than reflecting it.
if settings.all_cors_origins:
    _wildcard = "*" in settings.all_cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=not _wildcard,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# The settings a browser can break on, in the logs, once, at boot. Every value
# here is derived from FRONTEND_HOST or from credentials set per deployment, and
# when one of them is wrong the symptom appears in the *browser* — a blocked
# response or a failed sign-in — while the API's own logs show healthy 200s.
# Reading them back is the difference between diagnosing that in a minute and
# guessing at it. The client ID is public (it ships in the dashboard bundle);
# the secret is reported only as present or absent.
logger.info(
    "Public config: environment=%s frontend_host=%s cors_origins=%s "
    "github_oauth_redirect_uri=%s github_client_id=%s github_client_secret=%s",
    settings.ENVIRONMENT,
    settings.FRONTEND_HOST,
    settings.all_cors_origins,
    settings.GITHUB_OAUTH_REDIRECT_URI,
    settings.GITHUB_CLIENT_ID or "<unset>",
    "set" if settings.GITHUB_CLIENT_SECRET else "<unset>",
)

# Rate limiting. Limits are attached per route by api.router.RoleRouter rather
# than by slowapi's middleware — see the note in core/rate_limit.py for why the
# middleware cannot see FastAPI 0.141's lazily-included routes. Only the
# exception handler is app-level; app.state.limiter is what slowapi's own
# machinery reaches for.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

app.include_router(api_router, prefix=settings.API_V1_STR)
