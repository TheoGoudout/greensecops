"""Request-frequency limiting for the HTTP API.

Deliberately distinct from the billing quota system in ``services/billing``:
that meters a *paid allowance* over a billing period and answers 402, this caps
how fast anyone — paying or not — may call an endpoint, and answers 429. A
free-tier user with allowance left and an abusive script look identical to
quota accounting; they do not look alike here.

Every route gets ``settings.RATE_LIMIT_DEFAULT`` unless it declares its own
``limit=`` through ``api.router.RoleRouter``. The check runs as a FastAPI
dependency, so it happens before the endpoint body does any work.

Note on why there is no ``SlowAPIMiddleware`` here. slowapi's middleware finds
the route for a request with ``_find_route_handler``, which scans ``app.routes``
for something with an ``.endpoint`` attribute. Since FastAPI 0.141 an included
router is left in ``app.routes`` as a lazy ``_IncludedRouter`` wrapper rather
than being spliced in, so that scan finds nothing, ``_should_exempt`` returns
True for every request, and the middleware silently rate-limits nothing at all.
Attaching the limit per route sidesteps that entirely — and keeps an ASGI layer
out from in front of the SSE stream, which it has no business buffering.
"""

import time
from collections.abc import Callable
from typing import Any, Final

import jwt
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from jwt.exceptions import InvalidTokenError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from app.core import security
from app.core.config import settings

NO_RATE_LIMIT: Final = "__no_rate_limit__"
"""Sentinel for the rare endpoint that must never be throttled."""

# ─── Limit tiers ──────────────────────────────────────────────────────────────
#
# Endpoints without an explicit tier ride settings.RATE_LIMIT_DEFAULT. The
# numbers assume the key is a single user (or a single IP for anonymous
# callers), not the whole deployment.

# Credential endpoints. Low enough to make online password/token guessing
# useless, high enough that a human fat-fingering a login never notices.
LIMIT_AUTH = "10/minute"

# Unauthenticated public reads (badges). Keyed by IP, and badges are cached by
# GitHub's camo proxy in practice, so real traffic sits far below this.
LIMIT_PUBLIC = "60/minute"

# SSE connection attempts. One browser tab needs one connection; a reconnect
# storm is the thing worth capping.
LIMIT_STREAM = "12/minute"

# Anything that dispatches Celery work or fans out to the GitHub API. These
# cost real money (LLM calls) and real quota (GitHub's 5000 req/h), so they are
# the endpoints most worth protecting from a runaway client.
LIMIT_EXPENSIVE = "20/minute"

# GitHub Actions telemetry ingest. Keyed by runner IP rather than user (the
# OIDC token is RS256 and does not decode as one of ours), and a busy matrix
# build legitimately posts many runs at once.
LIMIT_INGEST = "120/minute"

# Inbound provider webhooks. GitHub fans out one delivery per event and a large
# push can burst hard; this is a runaway-loop backstop, not a throttle.
LIMIT_WEBHOOK = "600/minute"


def _client_ip(request: Request) -> str:
    if settings.RATE_LIMIT_TRUST_PROXY_HEADERS:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Left-most entry is the original client; the rest are proxies.
            return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit_key(request: Request) -> str:
    """Identify the caller: the authenticated user when possible, else address.

    Decoding the JWT here costs no database round-trip, and the signature is
    still verified, so the subject cannot be forged to steal someone else's
    budget. An unparseable or foreign token (GitHub's RS256 OIDC tokens, for
    instance) simply falls through to address keying.

    Keying by user rather than address matters behind CGNAT and corporate
    egress, where thousands of unrelated users share one address.
    """
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        try:
            payload = jwt.decode(
                authorization.removeprefix("Bearer "),
                settings.SECRET_KEY,
                algorithms=[security.ALGORITHM],
            )
        except InvalidTokenError:
            pass
        else:
            subject = payload.get("sub")
            if subject:
                return f"user:{subject}"
    return f"ip:{_client_ip(request)}"


limiter = Limiter(
    key_func=rate_limit_key,
    storage_uri=settings.rate_limit_storage_uri,
    # Bucket per endpoint, not per URL. slowapi's default ("url") keys on the
    # concrete request path, so /repositories/<a>/toggle and
    # /repositories/<b>/toggle would draw on separate budgets and a caller could
    # sidestep any limit on a parameterised route just by varying the id.
    key_style="endpoint",
    # Left off deliberately. slowapi's per-route decorator injects headers into
    # whatever the endpoint returned, and for an endpoint returning a model or
    # dict rather than a Response it reaches for a `response: Response`
    # parameter instead — which would mean adding one to all 40-odd rate-limited
    # endpoints purely to decorate the happy path. The numbers only become
    # actionable once a caller is actually being throttled, so
    # rate_limit_exceeded_handler puts them on the 429 instead.
    headers_enabled=False,
    # A Redis outage must not take the API down with it. Falling back to
    # per-process counters loses cross-worker accuracy but keeps the limit
    # roughly in force — the same fail-soft posture as the webhook delivery
    # dedup in api/routes/webhooks.py.
    in_memory_fallback_enabled=True,
    enabled=settings.RATE_LIMIT_ENABLED,
)


def rate_limit_dependency(
    limit_value: str, endpoint: Callable[..., Any]
) -> Callable[..., None]:
    """Build the dependency that enforces ``limit_value`` for one endpoint.

    slowapi's ``limit()`` decorator insists on a parameter literally named
    ``request`` on whatever it wraps. Wrapping the *endpoint* would therefore
    mean adding a ``request: Request`` parameter — unused, and needing a ruff
    suppression — to well over a hundred handlers. Wrapping a tiny dependency
    instead puts that parameter in exactly one place, and a dependency already
    runs before the endpoint body, which is when a limit wants to be checked.

    The dependency borrows the endpoint's ``__module__``/``__name__`` because
    that pair is how slowapi keys its counters: without it every endpoint would
    share this function's identity, and therefore one global bucket.
    """

    def check(request: Request) -> None:  # noqa: ARG001 — slowapi reads it by name
        """Raises RateLimitExceeded via slowapi's wrapper; nothing to do here."""
        return None

    check.__module__ = endpoint.__module__
    check.__name__ = endpoint.__name__
    check.__qualname__ = endpoint.__qualname__
    limited: Callable[..., None] = limiter.limit(limit_value)(check)
    return limited


def _throttle_headers(request: Request) -> dict[str, str]:
    """Standard rate-limit headers describing the limit the caller just hit."""
    current = getattr(request.state, "view_rate_limit", None)
    if current is None:  # pragma: no cover - slowapi always sets this first
        return {}
    item, key = current
    try:
        reset_at, remaining = limiter.limiter.get_window_stats(item, *key)
    except Exception:  # pragma: no cover - storage went away mid-request
        return {}
    return {
        # Never advertise 0: a client honouring it literally would retry in a
        # tight loop against the very limit it just tripped.
        "Retry-After": str(max(1, int(reset_at - time.time()))),
        "X-RateLimit-Limit": str(item.amount),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(int(reset_at)),
    }


def rate_limit_exceeded_handler(request: Request, exc: Exception) -> Response:
    """Render a 429 in this API's error shape.

    slowapi's stock handler answers ``{"error": ...}``; every other error in
    this API answers ``{"detail": ...}``, and the frontend's
    ``extractErrorMessage`` only knows that shape — an ``{"error": ...}`` body
    would surface to the user as "undefined". The machine-readable half goes in
    headers, where HTTP clients already look for it, so nothing on the frontend
    has to learn a new payload.
    """
    if not isinstance(exc, RateLimitExceeded):  # pragma: no cover - defensive
        raise exc
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}. Please retry shortly."},
        headers=_throttle_headers(request),
    )
