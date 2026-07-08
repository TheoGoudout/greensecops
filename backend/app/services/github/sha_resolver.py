import logging
import re
from typing import Any

import httpx
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_ACTION_USE_RE = re.compile(r"uses:\s+([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)@([^\s#]+)")

# Actions commonly introduced by the LLM when fixing workflows. Their latest
# versions are resolved online so the LLM never invents hashes or pins to a
# stale hardcoded tag.
WELL_KNOWN_ACTIONS: list[str] = [
    "actions/checkout",
    "actions/setup-python",
    "actions/cache",
    "actions/upload-artifact",
    "actions/download-artifact",
]

# GitHub tags and release history are effectively immutable; a day-long cache
# keeps unauthenticated API usage far below the 60 req/h rate limit.
_CACHE_TTL = 24 * 60 * 60
_SHA_CACHE_PREFIX = "action_sha:"
_VERSION_CACHE_PREFIX = "action_version:latest:"


def _parse_action_refs(workflow_content: str) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    for match in _ACTION_USE_RE.finditer(workflow_content):
        repo, ref = match.group(1), match.group(2)
        if re.fullmatch(r"[0-9a-f]{40}", ref):
            continue
        refs.add((repo, ref))
    return refs


async def _cache_get(cache: aioredis.Redis | None, key: str) -> str | None:
    if cache is None:
        return None
    try:
        value = await cache.get(key)
        return value.decode() if isinstance(value, bytes) else value
    except Exception:
        logger.warning("Redis cache read failed for %s", key, exc_info=True)
        return None


async def _cache_set(cache: aioredis.Redis | None, key: str, value: str) -> None:
    if cache is None:
        return
    try:
        await cache.setex(key, _CACHE_TTL, value)
    except Exception:
        logger.warning("Redis cache write failed for %s", key, exc_info=True)


async def _resolve_ref_to_sha(
    client: httpx.AsyncClient, repo: str, ref: str
) -> str | None:
    for url in [
        f"https://api.github.com/repos/{repo}/git/ref/tags/{ref}",
        f"https://api.github.com/repos/{repo}/git/ref/heads/{ref}",
    ]:
        try:
            resp = await client.get(url, timeout=10.0)
            if resp.status_code != 200:
                continue
            data: dict[str, Any] = resp.json()
            obj = data.get("object", {})
            sha: str = obj.get("sha", "")
            if obj.get("type") == "tag":
                tag_resp = await client.get(obj.get("url", ""), timeout=10.0)
                if tag_resp.status_code == 200:
                    sha = tag_resp.json().get("object", {}).get("sha", sha)
            return sha or None
        except Exception as exc:
            logger.warning("Failed to resolve SHA for %s@%s: %s", repo, ref, exc)
    return None


async def _cached_resolve_ref_to_sha(
    client: httpx.AsyncClient, cache: aioredis.Redis | None, repo: str, ref: str
) -> str | None:
    cache_key = f"{_SHA_CACHE_PREFIX}{repo}@{ref}"
    sha = await _cache_get(cache, cache_key)
    if sha:
        return sha
    sha = await _resolve_ref_to_sha(client, repo, ref)
    if sha:
        await _cache_set(cache, cache_key, sha)
    return sha


async def _get_latest_version(client: httpx.AsyncClient, repo: str) -> str | None:
    """Latest release tag of an action repo, falling back to the newest tag."""
    try:
        resp = await client.get(
            f"https://api.github.com/repos/{repo}/releases/latest", timeout=10.0
        )
        if resp.status_code == 200:
            tag: str = resp.json().get("tag_name", "")
            if tag:
                return tag
        resp = await client.get(
            f"https://api.github.com/repos/{repo}/tags?per_page=1", timeout=10.0
        )
        if resp.status_code == 200:
            tags = resp.json()
            if tags:
                name: str = tags[0].get("name", "")
                return name or None
    except Exception as exc:
        logger.warning("Failed to resolve latest version for %s: %s", repo, exc)
    return None


async def _cached_get_latest_version(
    client: httpx.AsyncClient, cache: aioredis.Redis | None, repo: str
) -> str | None:
    cache_key = f"{_VERSION_CACHE_PREFIX}{repo}"
    version = await _cache_get(cache, cache_key)
    if version:
        return version
    version = await _get_latest_version(client, repo)
    if version:
        await _cache_set(cache, cache_key, version)
    return version


async def resolve_action_shas(workflow_content: str) -> dict[str, str]:
    """Return a map of 'owner/repo@ref' -> commit SHA for the LLM prompt.

    Covers every pinnable ref in the workflow, plus the latest version of each
    referenced and well-known action (fetched online). All lookups are cached
    in Redis; on cache failure the resolver falls back to direct API calls.
    """
    refs = _parse_action_refs(workflow_content)
    repos = {repo for repo, _ in refs} | set(WELL_KNOWN_ACTIONS)

    cache: aioredis.Redis | None = None
    try:
        from app.core.config import settings

        cache = aioredis.from_url(settings.REDIS_URL)
    except Exception:
        logger.warning("Redis unavailable for action SHA cache", exc_info=True)

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    sha_map: dict[str, str] = {}
    try:
        async with httpx.AsyncClient(headers=headers) as client:
            for repo in sorted(repos):
                latest = await _cached_get_latest_version(client, cache, repo)
                if latest:
                    refs.add((repo, latest))
            for repo, ref in sorted(refs):
                sha = await _cached_resolve_ref_to_sha(client, cache, repo, ref)
                if sha:
                    sha_map[f"{repo}@{ref}"] = sha
    finally:
        if cache is not None:
            try:
                await cache.aclose()
            except Exception:
                pass

    return sha_map
