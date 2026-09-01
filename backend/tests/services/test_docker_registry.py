"""Base-image digest resolution: what is asked, and what an absent answer means.

Every case here drives ``httpx`` through a ``MockTransport`` rather than the
network — the suite must not depend on Docker Hub being up, and the point being
pinned is the *protocol* (token challenge, manifest accept types, the digest
header) rather than any particular image's current digest.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.docker import registry
from app.services.docker.dockerfile_parser import parse_dockerfile_content

_DIGEST = "sha256:" + "ab" * 32


def _dockerfile(text: str) -> dict:
    parsed = parse_dockerfile_content("Dockerfile", text)
    assert parsed is not None
    return parsed


# ─── Reference splitting ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("image", "expected"),
    [
        # An unqualified single-segment name is a Docker Hub official image.
        ("python", ("docker.io", "library/python")),
        # Two segments with no host is still Docker Hub, just not `library`.
        ("myorg/app", ("docker.io", "myorg/app")),
        ("ghcr.io/myorg/app", ("ghcr.io", "myorg/app")),
        ("quay.io/prometheus/node-exporter", ("quay.io", "prometheus/node-exporter")),
        # A port makes it a host; without one, `localhost` still is.
        ("localhost:5000/app", ("localhost:5000", "app")),
        ("localhost/app", ("localhost", "app")),
    ],
)
def test_split_reference(image: str, expected: tuple[str, str]) -> None:
    assert registry.split_reference(image) == expected


# ─── Which references get looked up ──────────────────────────────────────────


def test_only_unpinned_registry_images_are_resolved() -> None:
    """Mirrors the rule's own exclusions, so the prompt is offered exactly the
    references ``unpinned_base_image`` would flag."""
    parsed = _dockerfile(
        f"""FROM python:3.12-slim AS builder
FROM node@{_DIGEST} AS web
FROM scratch
FROM builder
FROM redis
"""
    )
    assert registry.unpinned_base_images(parsed) == [
        ("python", "3.12-slim"),
        # A FROM with no tag means :latest, which is exactly what the rule is
        # complaining about.
        ("redis", "latest"),
    ]


def test_the_same_base_image_twice_is_resolved_once() -> None:
    parsed = _dockerfile(
        """FROM python:3.12-slim AS builder
FROM python:3.12-slim AS runtime
"""
    )
    assert registry.unpinned_base_images(parsed) == [("python", "3.12-slim")]


def test_a_build_arg_image_is_not_looked_up() -> None:
    """`FROM $BASE` names nothing a registry could answer for."""
    parsed = _dockerfile("ARG BASE\nFROM $BASE\n")
    assert registry.unpinned_base_images(parsed) == []


# ─── Talking to a registry ───────────────────────────────────────────────────


def _transport(
    *,
    digest: str | None = _DIGEST,
    manifest_status: int = 200,
    head_status: int | None = None,
) -> httpx.MockTransport:
    """A registry that demands a token, then answers the manifest request."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path.endswith("/tags/list"):
            return httpx.Response(
                401,
                headers={
                    "www-authenticate": (
                        'Bearer realm="https://auth.example/token",'
                        'service="registry.example"'
                    )
                },
            )
        if path == "/token":
            return httpx.Response(200, json={"token": "tok-123"})
        headers = {"docker-content-digest": digest} if digest else {}
        status = (
            head_status
            if head_status is not None and request.method == "HEAD"
            else manifest_status
        )
        return httpx.Response(status, headers=headers)

    transport = httpx.MockTransport(handler)
    transport.seen = seen  # type: ignore[attr-defined]
    return transport


@pytest.fixture()
def mock_registry(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Route the resolver's client at a fake registry, and skip Redis."""

    def install(transport: httpx.MockTransport) -> httpx.MockTransport:
        original = httpx.AsyncClient

        def factory(**kwargs: object) -> httpx.AsyncClient:
            kwargs.pop("transport", None)
            return original(transport=transport, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(registry.httpx, "AsyncClient", factory)
        # No cache: `cached_fetch` falls straight through to the fetch, which is
        # what these cases are about.
        monkeypatch.setattr(registry, "open_cache", lambda: None)
        return transport

    return install


def test_digest_is_read_from_the_manifest_response(mock_registry) -> None:  # type: ignore[no-untyped-def]
    transport = mock_registry(_transport())
    parsed = _dockerfile("FROM python:3.12-slim\n")

    assert asyncio.run(registry.resolve_base_image_digests(parsed)) == {
        "python:3.12-slim": _DIGEST
    }

    manifest = [r for r in transport.seen if "/manifests/" in r.url.path][-1]
    # Docker Hub's API host, not the `docker.io` name in the reference.
    assert manifest.url.host == "registry-1.docker.io"
    assert manifest.url.path == "/v2/library/python/manifests/3.12-slim"
    assert manifest.headers["Authorization"] == "Bearer tok-123"
    # Without the index types a multi-arch image answers 404 rather than a digest.
    assert "application/vnd.oci.image.index.v1+json" in manifest.headers["Accept"]


def test_a_registry_that_rejects_head_is_retried_with_get(mock_registry) -> None:  # type: ignore[no-untyped-def]
    transport = mock_registry(_transport(head_status=405))
    parsed = _dockerfile("FROM python:3.12-slim\n")

    assert asyncio.run(registry.resolve_base_image_digests(parsed)) == {
        "python:3.12-slim": _DIGEST
    }
    methods = [r.method for r in transport.seen if "/manifests/" in r.url.path]
    assert methods == ["HEAD", "GET"]


def test_an_unknown_tag_resolves_to_nothing(mock_registry) -> None:  # type: ignore[no-untyped-def]
    """A 404 leaves the reference out of the map entirely.

    That absence is the instruction: the prompt says only listed digests may be
    written, so an unresolved image keeps whatever it has.
    """
    mock_registry(_transport(manifest_status=404))
    parsed = _dockerfile("FROM python:nope\n")

    assert asyncio.run(registry.resolve_base_image_digests(parsed)) == {}


def test_a_response_without_a_digest_header_resolves_to_nothing(  # type: ignore[no-untyped-def]
    mock_registry,
) -> None:
    mock_registry(_transport(digest=None))
    parsed = _dockerfile("FROM python:3.12-slim\n")

    assert asyncio.run(registry.resolve_base_image_digests(parsed)) == {}


def test_a_malformed_digest_is_refused(mock_registry) -> None:  # type: ignore[no-untyped-def]
    """Never hand the model something that is not a sha256 digest."""
    mock_registry(_transport(digest="not-a-digest"))
    parsed = _dockerfile("FROM python:3.12-slim\n")

    assert asyncio.run(registry.resolve_base_image_digests(parsed)) == {}


def test_an_unreachable_registry_resolves_to_nothing(  # type: ignore[no-untyped-def]
    mock_registry,
) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    mock_registry(httpx.MockTransport(boom))
    parsed = _dockerfile("FROM python:3.12-slim\n")

    assert asyncio.run(registry.resolve_base_image_digests(parsed)) == {}


def test_nothing_to_resolve_makes_no_requests(mock_registry) -> None:  # type: ignore[no-untyped-def]
    transport = mock_registry(_transport())
    parsed = _dockerfile(f"FROM python:3.12-slim@{_DIGEST}\n")

    assert asyncio.run(registry.resolve_base_image_digests(parsed)) == {}
    assert transport.seen == []
