"""Tests for the GitHub action SHA resolver."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.github.sha_resolver import (
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


def _fake_async_client_ctx(*responses: FakeResponse) -> MagicMock:
    client = _fake_client(*responses)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=ctx)


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


def test_resolve_action_shas_empty_workflow() -> None:
    assert asyncio.run(resolve_action_shas("")) == {}


def test_resolve_action_shas_all_already_pinned() -> None:
    sha = "a" * 40
    assert (
        asyncio.run(resolve_action_shas(f"      - uses: actions/checkout@{sha}\n"))
        == {}
    )


def test_resolve_action_shas_resolves_single_action() -> None:
    workflow = "      - uses: actions/checkout@v4\n"
    resp = FakeResponse({"object": {"sha": "resolved_sha", "type": "commit"}})
    factory = _fake_async_client_ctx(resp)

    with patch("app.services.github.sha_resolver.httpx.AsyncClient", factory):
        result = asyncio.run(resolve_action_shas(workflow))

    assert result == {"actions/checkout@v4": "resolved_sha"}


def test_resolve_action_shas_skips_unresolvable_action() -> None:
    workflow = "      - uses: actions/checkout@v4\n"
    factory = _fake_async_client_ctx(FakeResponse({}, 404), FakeResponse({}, 404))

    with patch("app.services.github.sha_resolver.httpx.AsyncClient", factory):
        result = asyncio.run(resolve_action_shas(workflow))

    assert result == {}
