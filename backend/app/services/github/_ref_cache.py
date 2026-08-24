"""Redis caching for GitHub ref lookups, shared by the two callers that do them.

``sha_resolver`` (which feeds the fix-generation prompt) and ``action_metadata``
(which feeds the analysis rules) ask GitHub the same kind of question and want
the same stampede protection. This was inlined in the first of them; the second
needed it too, and a second copy of a cache is a second set of TTLs to keep in
step.

The one thing lifted rather than copied verbatim is the TTL: the original was a
flat 24 hours, which is right for a resolved answer and wrong for a failed one.
``ttl_for`` lets the caller decide per value, so a rate-limit window cannot
silence a rule for a day.
"""

import logging
from collections.abc import Awaitable, Callable

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_TTL = 24 * 60 * 60


def open_cache() -> aioredis.Redis | None:
    try:
        return aioredis.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call,no-any-return]
    except Exception:
        logger.warning("Redis unavailable for GitHub ref cache", exc_info=True)
        return None


async def close_cache(cache: aioredis.Redis | None) -> None:
    if cache is None:
        return
    try:
        await cache.aclose()
    except Exception:
        pass


async def cache_get(cache: aioredis.Redis | None, key: str) -> str | None:
    if cache is None:
        return None
    try:
        value = await cache.get(key)
        return value.decode() if isinstance(value, bytes) else value
    except Exception:
        logger.warning("Redis cache read failed for %s", key, exc_info=True)
        return None


async def cache_set(
    cache: aioredis.Redis | None, key: str, value: str, ttl: int
) -> None:
    if cache is None:
        return
    try:
        await cache.setex(key, ttl, value)
    except Exception:
        logger.warning("Redis cache write failed for %s", key, exc_info=True)


async def cached_fetch(
    cache: aioredis.Redis | None,
    cache_key: str,
    fetch_fn: Callable[[], Awaitable[str | None]],
    *,
    ttl_for: Callable[[str], int] | None = None,
) -> str | None:
    """Get from cache, or fetch under a lock to prevent a stampede.

    The double-check-lock pattern (check → lock → recheck → fetch) ensures that
    when several workers miss the cache at once, only the first calls the GitHub
    API; the rest read what it stored.
    """

    def ttl(value: str) -> int:
        return ttl_for(value) if ttl_for else DEFAULT_TTL

    value = await cache_get(cache, cache_key)
    if value:
        return value
    if cache is not None:
        try:
            async with cache.lock(f"lock:{cache_key}", timeout=30, blocking_timeout=35):
                value = await cache_get(cache, cache_key)
                if value:
                    return value
                value = await fetch_fn()
                if value:
                    await cache_set(cache, cache_key, value, ttl(value))
                return value
        except Exception:
            logger.warning("Redis lock failed for %s", cache_key, exc_info=True)
    value = await fetch_fn()
    if value:
        await cache_set(cache, cache_key, value, ttl(value))
    return value
