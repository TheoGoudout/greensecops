"""Redis pub/sub event publisher.

Celery tasks run in separate worker processes and cannot use async Redis.
Route handlers run in FastAPI and can use async Redis.

Both call publish_event() — it auto-detects the calling context and picks
the right client.
"""

import logging

from app.services.events.schemas import SSEEvent

logger = logging.getLogger(__name__)

_CHANNEL_PREFIX = "events:org"


def _channel(org_id: str) -> str:
    return f"{_CHANNEL_PREFIX}:{org_id}"


def publish_event(event: SSEEvent) -> None:
    """Publish from a Celery worker (sync). Fire-and-forget — never raises."""
    try:
        import redis

        from app.core.config import settings

        client = redis.from_url(settings.REDIS_URL)
        try:
            client.publish(_channel(event.org_id), event.to_wire())
        finally:
            client.close()
    except Exception:
        logger.exception(
            "Failed to publish SSE event %s for org %s", event.event, event.org_id
        )


async def publish_event_async(event: SSEEvent) -> None:
    """Publish from a FastAPI route handler (async). Fire-and-forget — never raises."""
    try:
        import redis.asyncio as aioredis

        from app.core.config import settings

        client = aioredis.from_url(settings.REDIS_URL)
        try:
            await client.publish(_channel(event.org_id), event.to_wire())
        finally:
            await client.aclose()
    except Exception:
        logger.exception(
            "Failed to publish SSE event %s for org %s", event.event, event.org_id
        )
