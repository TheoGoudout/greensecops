import sentry_sdk
from fastapi import FastAPI
from fastapi.routing import APIRoute
from slowapi.errors import RateLimitExceeded
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings
from app.core.rate_limit import limiter, rate_limit_exceeded_handler


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(
    title=settings.PROJECT_NAME,
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

# Rate limiting. Limits are attached per route by api.router.RoleRouter rather
# than by slowapi's middleware — see the note in core/rate_limit.py for why the
# middleware cannot see FastAPI 0.141's lazily-included routes. Only the
# exception handler is app-level; app.state.limiter is what slowapi's own
# machinery reaches for.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

app.include_router(api_router, prefix=settings.API_V1_STR)
