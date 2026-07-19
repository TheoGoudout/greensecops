import asyncio
import logging
import re
from collections.abc import Awaitable, Callable

import redis.asyncio as aioredis
from github import Github
from github.GithubException import GithubException, UnknownObjectException

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
# keeps API usage far below rate limits.
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


def _resolve_ref_to_sha_sync(gh: Github, repo_name: str, ref: str) -> str | None:
    try:
        repo = gh.get_repo(repo_name)
    except (GithubException, UnknownObjectException) as exc:
        logger.warning("Failed to get repo %s: %s", repo_name, exc)
        return None

    for ref_path in [f"tags/{ref}", f"heads/{ref}"]:
        try:
            git_ref = repo.get_git_ref(ref_path)
            sha = git_ref.object.sha
            if git_ref.object.type == "tag":
                sha = repo.get_git_tag(sha).object.sha
            return sha
        except (GithubException, UnknownObjectException):
            continue
        except Exception as exc:
            logger.warning("Failed to resolve SHA for %s@%s: %s", repo_name, ref, exc)
    return None


def _get_latest_version_sync(gh: Github, repo_name: str) -> str | None:
    """Latest release tag of an action repo, falling back to the newest tag."""
    try:
        repo = gh.get_repo(repo_name)
    except (GithubException, UnknownObjectException) as exc:
        logger.warning("Failed to get repo %s: %s", repo_name, exc)
        return None

    try:
        return repo.get_latest_release().tag_name
    except GithubException:
        pass

    try:
        tag = next(iter(repo.get_tags()), None)
        return tag.name if tag else None
    except Exception as exc:
        logger.warning("Failed to resolve latest version for %s: %s", repo_name, exc)
    return None


async def _cached_fetch(
    cache: aioredis.Redis | None,
    cache_key: str,
    fetch_fn: Callable[[], Awaitable[str | None]],
) -> str | None:
    """Get from cache, or fetch with a Redis lock to prevent cache stampede.

    The double-check-lock pattern (check → lock → recheck → fetch) ensures that
    when multiple workers miss the cache simultaneously, only the first one calls
    the GitHub API; the rest read the value populated under the lock.
    """
    value = await _cache_get(cache, cache_key)
    if value:
        return value
    if cache is not None:
        try:
            async with cache.lock(f"lock:{cache_key}", timeout=30, blocking_timeout=35):
                value = await _cache_get(cache, cache_key)
                if value:
                    return value
                value = await fetch_fn()
                if value:
                    await _cache_set(cache, cache_key, value)
                return value
        except Exception:
            logger.warning("Redis lock failed for %s", cache_key, exc_info=True)
    value = await fetch_fn()
    if value:
        await _cache_set(cache, cache_key, value)
    return value


async def _cached_resolve_ref_to_sha(
    gh: Github, cache: aioredis.Redis | None, repo: str, ref: str
) -> str | None:
    return await _cached_fetch(
        cache,
        f"{_SHA_CACHE_PREFIX}{repo}@{ref}",
        lambda: asyncio.to_thread(_resolve_ref_to_sha_sync, gh, repo, ref),
    )


async def _cached_get_latest_version(
    gh: Github, cache: aioredis.Redis | None, repo: str
) -> str | None:
    return await _cached_fetch(
        cache,
        f"{_VERSION_CACHE_PREFIX}{repo}",
        lambda: asyncio.to_thread(_get_latest_version_sync, gh, repo),
    )


async def resolve_action_shas(
    workflow_content: str, gh: Github | None = None
) -> dict[str, str]:
    """Return a map of 'owner/repo@ref' -> commit SHA for the LLM prompt.

    Covers every pinnable ref in the workflow, plus the latest version of each
    referenced and well-known action (fetched online). All lookups are cached
    in Redis with a 24-hour TTL; on cache failure the resolver falls back to
    direct API calls.

    Pass an authenticated ``gh`` instance (e.g. built from a GitHub App
    installation token) to use the 5 000 req/h authenticated rate limit instead
    of the 60 req/h unauthenticated limit. When omitted an unauthenticated
    client is created as a fallback.
    """
    refs = _parse_action_refs(workflow_content)
    repos = {repo for repo, _ in refs} | set(WELL_KNOWN_ACTIONS)

    cache: aioredis.Redis | None = None
    try:
        from app.core.config import settings

        cache = aioredis.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call]
    except Exception:
        logger.warning("Redis unavailable for action SHA cache", exc_info=True)

    if gh is None:
        gh = Github()

    sha_map: dict[str, str] = {}
    try:
        for repo in sorted(repos):
            latest = await _cached_get_latest_version(gh, cache, repo)
            if latest:
                refs.add((repo, latest))
        for repo, ref in sorted(refs):
            sha = await _cached_resolve_ref_to_sha(gh, cache, repo, ref)
            if sha:
                sha_map[f"{repo}@{ref}"] = sha
    finally:
        if cache is not None:
            try:
                await cache.aclose()
            except Exception:
                pass

    return sha_map
