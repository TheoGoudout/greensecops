"""Tests for the GitHub action SHA resolver."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.github.sha_resolver import (
    WELL_KNOWN_ACTIONS,
    _parse_action_refs,
    _resolve_ref_to_sha,
    resolve_action_shas,
)

# ─── helpers ─────────────────────────────────────────────────────────────────


class FakeResponse:
    def __init__(self, json_data: Any, status_code: int = 200) -> None:
        self._json = json_data
        self.status_code = status_code

    def json(self) -> Any:
        return self._json


def _fake_client(*responses: FakeResponse) -> MagicMock:
    client = MagicMock()
    client.get = AsyncMock(side_effect=list(responses))
    return client


def _routing_client(routes: dict[str, FakeResponse]) -> MagicMock:
    """Client whose GET responses are keyed by URL substring; 404 otherwise."""

    async def _get(url: str, **_: Any) -> FakeResponse:
        for fragment, resp in routes.items():
            if fragment in url:
                return resp
        return FakeResponse({}, status_code=404)

    client = MagicMock()
    client.get = AsyncMock(side_effect=_get)
    return client


def _fake_async_client_ctx(client: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=ctx)


def _fake_cache(store: dict[str, str] | None = None) -> MagicMock:
    store = store if store is not None else {}
    cache = MagicMock()

    async def _get(key: str) -> str | None:
        return store.get(key)

    async def _setex(key: str, _ttl: int, value: str) -> None:
        store[key] = value

    cache.get = AsyncMock(side_effect=_get)
    cache.setex = AsyncMock(side_effect=_setex)
    cache.aclose = AsyncMock()
    cache._store = store
    return cache


def _resolve(workflow: str, client: MagicMock, cache: MagicMock) -> dict[str, str]:
    with (
        patch(
            "app.services.github.sha_resolver.httpx.AsyncClient",
            _fake_async_client_ctx(client),
        ),
        patch(
            "app.services.github.sha_resolver.aioredis.from_url",
            return_value=cache,
        ),
    ):
        return asyncio.run(resolve_action_shas(workflow))


# ─── _parse_action_refs ───────────────────────────────────────────────────────


def test_parse_action_refs_extracts_tag_ref() -> None:
    workflow = "      - uses: actions/checkout@v4\n"
    assert _parse_action_refs(workflow) == {("actions/checkout", "v4")}


def test_parse_action_refs_skips_already_pinned_sha() -> None:
    sha = "a" * 40
    assert _parse_action_refs(f"      - uses: actions/checkout@{sha}\n") == set()


def test_parse_action_refs_multiple_actions() -> None:
    workflow = (
        "      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n"
    )
    assert _parse_action_refs(workflow) == {
        ("actions/checkout", "v4"),
        ("actions/setup-python", "v5"),
    }


def test_parse_action_refs_deduplicates() -> None:
    workflow = "      - uses: actions/checkout@v4\n      - uses: actions/checkout@v4\n"
    assert _parse_action_refs(workflow) == {("actions/checkout", "v4")}


def test_parse_action_refs_empty_workflow() -> None:
    assert _parse_action_refs("") == set()


def test_parse_action_refs_no_uses() -> None:
    assert _parse_action_refs("name: CI\non: push\n") == set()


# ─── _resolve_ref_to_sha ─────────────────────────────────────────────────────


def test_resolve_ref_to_sha_lightweight_tag() -> None:
    resp = FakeResponse({"object": {"sha": "abc123", "type": "commit"}})
    sha = asyncio.run(_resolve_ref_to_sha(_fake_client(resp), "actions/checkout", "v4"))
    assert sha == "abc123"


def test_resolve_ref_to_sha_annotated_tag_dereferences() -> None:
    tag_ref = FakeResponse(
        {
            "object": {
                "sha": "tag_sha",
                "type": "tag",
                "url": "https://api.github.com/repos/actions/checkout/git/tags/tag_sha",
            }
        }
    )
    tag_obj = FakeResponse({"object": {"sha": "commit_sha", "type": "commit"}})
    sha = asyncio.run(
        _resolve_ref_to_sha(_fake_client(tag_ref, tag_obj), "actions/checkout", "v4")
    )
    assert sha == "commit_sha"


def test_resolve_ref_to_sha_tag_404_falls_back_to_branch() -> None:
    tag_404 = FakeResponse({}, status_code=404)
    branch = FakeResponse({"object": {"sha": "branch_sha", "type": "commit"}})
    sha = asyncio.run(
        _resolve_ref_to_sha(_fake_client(tag_404, branch), "actions/checkout", "main")
    )
    assert sha == "branch_sha"


def test_resolve_ref_to_sha_both_urls_fail() -> None:
    sha = asyncio.run(
        _resolve_ref_to_sha(
            _fake_client(FakeResponse({}, 404), FakeResponse({}, 404)),
            "actions/checkout",
            "v4",
        )
    )
    assert sha is None


def test_resolve_ref_to_sha_exception_returns_none() -> None:
    client = MagicMock()
    client.get = AsyncMock(side_effect=Exception("network error"))
    assert asyncio.run(_resolve_ref_to_sha(client, "actions/checkout", "v4")) is None


def test_resolve_ref_to_sha_empty_sha_returns_none() -> None:
    resp = FakeResponse({"object": {"sha": "", "type": "commit"}})
    assert (
        asyncio.run(_resolve_ref_to_sha(_fake_client(resp), "actions/checkout", "v4"))
        is None
    )


# ─── resolve_action_shas ─────────────────────────────────────────────────────


def test_resolve_action_shas_resolves_referenced_action() -> None:
    workflow = "      - uses: actions/checkout@v4\n"
    client = _routing_client(
        {
            "/git/ref/tags/": FakeResponse(
                {"object": {"sha": "resolved_sha", "type": "commit"}}
            ),
        }
    )
    result = _resolve(workflow, client, _fake_cache())
    assert result["actions/checkout@v4"] == "resolved_sha"


def test_resolve_action_shas_includes_latest_versions_of_well_known_actions() -> None:
    client = _routing_client(
        {
            "/releases/latest": FakeResponse({"tag_name": "v9"}),
            "/git/ref/tags/v9": FakeResponse(
                {"object": {"sha": "latest_sha", "type": "commit"}}
            ),
        }
    )
    result = _resolve("", client, _fake_cache())
    for repo in WELL_KNOWN_ACTIONS:
        assert result[f"{repo}@v9"] == "latest_sha"


def test_resolve_action_shas_latest_version_falls_back_to_tags() -> None:
    client = _routing_client(
        {
            "/tags?per_page=1": FakeResponse([{"name": "v7.1.2"}]),
            "/git/ref/tags/v7.1.2": FakeResponse(
                {"object": {"sha": "tag_sha", "type": "commit"}}
            ),
        }
    )
    result = _resolve("", client, _fake_cache())
    assert result["actions/checkout@v7.1.2"] == "tag_sha"


def test_resolve_action_shas_skips_unresolvable_action() -> None:
    workflow = "      - uses: someorg/private-action@v1\n"
    client = _routing_client({})  # everything 404s
    result = _resolve(workflow, client, _fake_cache())
    assert result == {}


def test_resolve_action_shas_uses_cached_values() -> None:
    workflow = "      - uses: actions/checkout@v4\n"
    store = {
        "action_sha:actions/checkout@v4": "cached_sha",
        "action_sha:actions/checkout@v9": "cached_latest_sha",
        "action_version:latest:actions/checkout": "v9",
    }
    for repo in WELL_KNOWN_ACTIONS:
        store.setdefault(f"action_version:latest:{repo}", "v9")
        store.setdefault(f"action_sha:{repo}@v9", "cached_latest_sha")

    client = _routing_client({})  # any HTTP call would 404 → sha missing
    result = _resolve(workflow, client, _fake_cache(store))

    assert result["actions/checkout@v4"] == "cached_sha"
    assert result["actions/checkout@v9"] == "cached_latest_sha"
    client.get.assert_not_called()


def test_resolve_action_shas_populates_cache() -> None:
    workflow = "      - uses: actions/checkout@v4\n"
    client = _routing_client(
        {
            "/releases/latest": FakeResponse({"tag_name": "v9"}),
            "/git/ref/tags/": FakeResponse(
                {"object": {"sha": "fresh_sha", "type": "commit"}}
            ),
        }
    )
    cache = _fake_cache()
    _resolve(workflow, client, cache)
    assert cache._store["action_sha:actions/checkout@v4"] == "fresh_sha"
    assert cache._store["action_version:latest:actions/checkout"] == "v9"


def test_resolve_action_shas_survives_redis_failure() -> None:
    workflow = "      - uses: actions/checkout@v4\n"
    client = _routing_client(
        {
            "/releases/latest": FakeResponse({"tag_name": "v9"}),
            "/git/ref/tags/": FakeResponse(
                {"object": {"sha": "resolved_sha", "type": "commit"}}
            ),
        }
    )
    with (
        patch(
            "app.services.github.sha_resolver.httpx.AsyncClient",
            _fake_async_client_ctx(client),
        ),
        patch(
            "app.services.github.sha_resolver.aioredis.from_url",
            side_effect=RuntimeError("redis down"),
        ),
    ):
        result = asyncio.run(resolve_action_shas(workflow))
    assert result["actions/checkout@v4"] == "resolved_sha"
