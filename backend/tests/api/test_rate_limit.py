"""Coverage for slowapi rate limiting.

The suite-wide conftest fixture disables the limiter, because the module-scoped
``client`` fixture shares counters across every test in a file. This module is
the one place it is switched back on, so everything that asserts throttling
behaviour lives here.

Storage is pinned to ``memory://`` rather than Redis: backend CI runs Postgres
only, and per-process counters are exactly right for a single test process.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from limits.storage import storage_from_string
from limits.strategies import FixedWindowRateLimiter

from app.core.config import settings
from app.core.rate_limit import (
    LIMIT_AUTH,
    _client_ip,
    rate_limit_key,
)
from app.core.rate_limit import limiter as app_limiter

LOGIN_URL = f"{settings.API_V1_STR}/login/access-token"
HEALTH_URL = f"{settings.API_V1_STR}/utils/health-check/"
# Declares no limit= of its own, so it rides settings.RATE_LIMIT_DEFAULT, and
# it touches no database, so hammering it stays cheap.
UNLIMITED_ROUTE_URL = f"{settings.API_V1_STR}/events/signals"


@pytest.fixture()
def limiter() -> Generator[None, None, None]:
    """Turn the limiter on, backed by fresh in-process counters."""
    app_limiter._storage = storage_from_string("memory://")
    app_limiter._limiter = FixedWindowRateLimiter(app_limiter._storage)
    app_limiter.enabled = True
    yield
    app_limiter.enabled = False


def _login_attempt(client: TestClient, email: str = "nobody@example.com"):
    return client.post(LOGIN_URL, data={"username": email, "password": "wrong"})


def test_auth_endpoint_throttles_credential_guessing(
    client: TestClient, limiter: None
) -> None:
    """LIMIT_AUTH exists to make online password guessing pointless."""
    allowed = int(LIMIT_AUTH.split("/")[0])

    codes = [_login_attempt(client).status_code for _ in range(allowed)]
    assert 429 not in codes, "throttled before the declared limit was reached"

    blocked = _login_attempt(client)
    assert blocked.status_code == 429
    assert "Rate limit exceeded" in blocked.json()["detail"]


def test_429_carries_retry_and_budget_headers(
    client: TestClient, limiter: None
) -> None:
    allowed = int(LIMIT_AUTH.split("/")[0])
    for _ in range(allowed + 1):
        response = _login_attempt(client)

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1
    assert response.headers["X-RateLimit-Limit"] == str(allowed)
    assert response.headers["X-RateLimit-Remaining"] == "0"
    assert int(response.headers["X-RateLimit-Reset"]) > 0


def test_429_uses_the_apis_error_shape(client: TestClient, limiter: None) -> None:
    """A ``detail`` string, not slowapi's ``{"error": ...}``.

    The frontend's extractErrorMessage only understands ``detail``; an ``error``
    key would surface to the user as "undefined".
    """
    for _ in range(int(LIMIT_AUTH.split("/")[0]) + 1):
        response = _login_attempt(client)

    body = response.json()
    assert "error" not in body
    assert isinstance(body["detail"], str)


def test_health_check_is_never_throttled(client: TestClient, limiter: None) -> None:
    """The container HEALTHCHECK polls this every 30s for the process's lifetime."""
    codes = {client.get(HEALTH_URL).status_code for _ in range(60)}
    assert codes == {200}


def test_default_limit_applies_to_undeclared_routes(
    client: TestClient, limiter: None
) -> None:
    """Routes without an explicit ``limit=`` still ride RATE_LIMIT_DEFAULT.

    This is the case slowapi's own middleware silently failed to cover under
    FastAPI 0.141 — see the note in core/rate_limit.py — so it is worth an
    end-to-end assertion rather than trusting the wiring.
    """
    allowed = int(settings.RATE_LIMIT_DEFAULT.split("/")[0])
    codes = [client.get(UNLIMITED_ROUTE_URL).status_code for _ in range(allowed + 1)]
    assert codes[-1] == 429
    assert codes.count(429) == 1


def test_disabled_limiter_lets_everything_through(client: TestClient) -> None:
    """No `limiter` fixture here — this is the state the rest of the suite runs in."""
    codes = {_login_attempt(client).status_code for _ in range(30)}
    assert 429 not in codes


# ─── Caller identity ──────────────────────────────────────────────────────────


class _FakeRequest:
    def __init__(self, headers: dict[str, str], host: str | None = "10.0.0.1") -> None:
        self.headers = headers
        self.client = type("C", (), {"host": host})() if host else None


def test_key_prefers_the_authenticated_user_over_the_address() -> None:
    """Behind CGNAT or a corporate egress, thousands of users share one address."""
    from datetime import timedelta

    from app.core.security import create_access_token

    user_id = "8ba1a0a2-0000-4000-8000-000000000001"
    token = create_access_token(user_id, expires_delta=timedelta(minutes=5))
    key = rate_limit_key(_FakeRequest({"Authorization": f"Bearer {token}"}))  # type: ignore[arg-type]
    assert key == f"user:{user_id}"


def test_key_falls_back_to_address_for_foreign_tokens() -> None:
    """GitHub's RS256 OIDC tokens are not ours and must not raise."""
    request = _FakeRequest({"Authorization": "Bearer not.a.real.token"})
    assert rate_limit_key(request) == "ip:10.0.0.1"  # type: ignore[arg-type]


def test_key_falls_back_to_address_when_unauthenticated() -> None:
    assert rate_limit_key(_FakeRequest({})) == "ip:10.0.0.1"  # type: ignore[arg-type]


def test_forwarded_for_is_ignored_unless_explicitly_trusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """X-Forwarded-For is caller-supplied: trusting it by default would let
    anyone mint an unlimited number of buckets."""
    request = _FakeRequest({"X-Forwarded-For": "1.2.3.4"})

    monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_PROXY_HEADERS", False)
    assert _client_ip(request) == "10.0.0.1"  # type: ignore[arg-type]

    monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_PROXY_HEADERS", True)
    assert _client_ip(request) == "1.2.3.4"  # type: ignore[arg-type]


def test_forwarded_for_takes_the_original_client_not_the_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_PROXY_HEADERS", True)
    request = _FakeRequest({"X-Forwarded-For": "1.2.3.4, 10.0.0.9, 10.0.0.10"})
    assert _client_ip(request) == "1.2.3.4"  # type: ignore[arg-type]


def test_address_of_last_resort() -> None:
    assert _client_ip(_FakeRequest({}, host=None)) == "unknown"  # type: ignore[arg-type]
