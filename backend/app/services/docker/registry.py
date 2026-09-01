"""Resolve a base-image reference to the digest it currently points at.

``unpinned_base_image`` asks for ``image:tag@sha256:...``, and the fix prompt
could not supply the digest half. The system prompt therefore told the model to
list the finding as unfixable rather than invent one — correct, and it meant
the rule was effectively never auto-fixed. This is the Docker counterpart of
``github/sha_resolver``: look the answer up, hand the model verified values,
and keep "never invent" as the rule for anything not on the list.

Only registries that answer an anonymous pull token are resolvable, which
covers the public base images this matters for. A private image simply does not
resolve, and an unresolved reference is left alone.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.services.ref_cache import cached_fetch, close_cache, open_cache

logger = logging.getLogger(__name__)

# Docker Hub is the implied registry for an unqualified name, and an
# unqualified single-segment name lives in the ``library`` namespace —
# ``FROM python`` is ``docker.io/library/python``.
_DEFAULT_REGISTRY = "docker.io"
_DEFAULT_NAMESPACE = "library"

# Where Docker Hub's registry API actually lives; ``docker.io`` is the name in
# the reference, not a host that serves the v2 API.
_REGISTRY_HOSTS = {"docker.io": "registry-1.docker.io"}

# Every manifest media type a base image can be published as. Without the OCI
# index types an image published as a multi-arch index answers 404 rather than
# the digest of its index.
_MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_CACHE_PREFIX = "image_digest:"

# A host is a registry rather than a namespace only if it looks like one: a dot,
# a colon, or the literal "localhost". `FROM myorg/app` is a Docker Hub name;
# `FROM ghcr.io/myorg/app` is not.
_HOSTLIKE = re.compile(r"[.:]|^localhost$")

_TIMEOUT = httpx.Timeout(10.0)


def split_reference(image: str) -> tuple[str, str]:
    """Split ``image`` into (registry host, repository path).

    ``python`` → ``("docker.io", "library/python")``
    ``myorg/app`` → ``("docker.io", "myorg/app")``
    ``ghcr.io/myorg/app`` → ``("ghcr.io", "myorg/app")``
    """
    head, _, rest = image.partition("/")
    if rest and _HOSTLIKE.search(head):
        return head, rest
    if "/" in image:
        return _DEFAULT_REGISTRY, image
    return _DEFAULT_REGISTRY, f"{_DEFAULT_NAMESPACE}/{image}"


async def _anonymous_token(
    client: httpx.AsyncClient, host: str, repository: str
) -> str | None:
    """Trade nothing for a pull-scoped token, the way `docker pull` does.

    A registry answers the manifest request with a 401 carrying a
    ``WWW-Authenticate: Bearer realm=...,service=...`` challenge; this asks that
    realm for a token scoped to one repository's pull. Returning ``None`` for a
    registry that will not issue one (a private image, an unknown host) is what
    makes the whole lookup fail closed.
    """
    try:
        probe = await client.get(f"https://{host}/v2/{repository}/tags/list")
    except httpx.HTTPError as exc:
        logger.warning("Registry %s unreachable: %s", host, exc)
        return None
    if probe.status_code != 401:
        # No challenge: either the registry allows anonymous reads outright, or
        # it is not speaking the v2 protocol. Either way there is no token.
        return None

    challenge = probe.headers.get("www-authenticate", "")
    fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    realm = fields.get("realm")
    if not realm:
        return None
    params: dict[str, str] = {"scope": f"repository:{repository}:pull"}
    if service := fields.get("service"):
        params["service"] = service
    try:
        response = await client.get(realm, params=params)
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Token request to %s failed: %s", realm, exc)
        return None
    token = payload.get("token") or payload.get("access_token")
    return str(token) if token else None


async def _fetch_digest(image: str, tag: str) -> str | None:
    """The digest ``image:tag`` resolves to right now, or ``None``.

    ``None`` covers every reason a lookup can fail — private repository,
    unknown tag, registry outage, a host that is not a registry at all. The
    caller treats them identically: no digest means the reference is left as it
    is, never guessed at.
    """
    host, repository = split_reference(image)
    api_host = _REGISTRY_HOSTS.get(host, host)
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        headers = {"Accept": _MANIFEST_ACCEPT}
        if token := await _anonymous_token(client, api_host, repository):
            headers["Authorization"] = f"Bearer {token}"
        url = f"https://{api_host}/v2/{repository}/manifests/{tag}"
        try:
            response = await client.head(url, headers=headers)
            # Not every registry answers HEAD on a manifest; fall back to GET,
            # which every v2 implementation must support.
            if response.status_code == 405:
                response = await client.get(url, headers=headers)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Digest lookup failed for %s:%s — %s", image, tag, exc)
            return None

    digest = str(response.headers.get("docker-content-digest", ""))
    if not _DIGEST_RE.fullmatch(digest):
        # A registry that answers without the header, or with something that is
        # not a sha256 digest, has told us nothing usable.
        return None
    return digest


def unpinned_base_images(dockerfile: dict[str, Any]) -> list[tuple[str, str]]:
    """The ``(image, tag)`` pairs in ``dockerfile`` that carry no digest.

    Mirrors ``unpinned_base_image``'s own exclusions so the prompt is offered
    digests for exactly the references the rule would flag: a stage that already
    has one needs nothing, ``scratch`` is the empty image, and a FROM naming an
    earlier stage is an internal reference rather than a registry pull.
    """
    stage_names = {
        stage.get("name") for stage in dockerfile.get("stages", []) if stage.get("name")
    }
    pairs: list[tuple[str, str]] = []
    for stage in dockerfile.get("stages", []):
        image = stage.get("image")
        if not image or stage.get("digest") or image in stage_names:
            continue
        if image == "scratch" or image.startswith("$"):
            continue
        pairs.append((image, stage.get("tag") or "latest"))
    # Deduplicated but order-preserving: two stages on the same base resolve once.
    return list(dict.fromkeys(pairs))


def _digest_fetcher(image: str, tag: str) -> Callable[[], Awaitable[str | None]]:
    """A zero-argument fetch for one reference, for ``cached_fetch`` to call."""

    async def fetch() -> str | None:
        return await _fetch_digest(image, tag)

    return fetch


async def resolve_base_image_digests(
    dockerfile: dict[str, Any],
) -> dict[str, str]:
    """Map ``image:tag`` to its current digest, for every unpinned base image.

    Absent entries are the point as much as present ones: the prompt states
    that only listed digests may be used, so a reference that could not be
    resolved is one the model must leave alone.
    """
    refs = unpinned_base_images(dockerfile)
    if not refs:
        return {}

    cache = open_cache()
    resolved: dict[str, str] = {}
    try:
        for image, tag in refs:
            key = f"{_CACHE_PREFIX}{image}:{tag}"
            # Bound in a helper rather than a default-argument lambda: the
            # closure has to capture *this* iteration's pair, and a lambda with
            # defaults is the version mypy cannot type.
            digest = await cached_fetch(cache, key, _digest_fetcher(image, tag))
            if digest:
                resolved[f"{image}:{tag}"] = digest
    finally:
        await close_cache(cache)
    return resolved
