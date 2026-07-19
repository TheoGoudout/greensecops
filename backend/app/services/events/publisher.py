"""Redis pub/sub event publisher.

publish_event() is sync and fire-and-forget; it is called from both Celery
workers and FastAPI route handlers.
"""

import logging

from app.services.events.schemas import SSEEvent

logger = logging.getLogger(__name__)

_CHANNEL_PREFIX = "events:org"


def _channel(org_id: str) -> str:
    return f"{_CHANNEL_PREFIX}:{org_id}"


def publish_event(event: SSEEvent) -> None:
    """Publish an event. Fire-and-forget — never raises."""
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
