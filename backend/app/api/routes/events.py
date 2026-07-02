import asyncio
import logging
from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlmodel import select

from app.api.deps import CurrentUserSSE, SessionDep
from app.core.config import settings
from app.models import OrgMember, SSESignal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])

_KEEPALIVE_SECONDS = 30
_CHANNEL_PREFIX = "events:org"


async def _stream_events(
    org_ids: list[str],
) -> AsyncGenerator[str, None]:
    """Subscribe to all org channels for this user and yield SSE frames."""
    if not org_ids:
        yield ": no-orgs\n\n"
        while True:
            await asyncio.sleep(_KEEPALIVE_SECONDS)
            yield ": keepalive\n\n"
        return

    r = aioredis.from_url(settings.REDIS_URL)
    pubsub = r.pubsub()
    channels = [f"{_CHANNEL_PREFIX}:{org_id}" for org_id in org_ids]

    try:
        await pubsub.subscribe(*channels)
        logger.debug("SSE subscribed to %d org channel(s)", len(channels))

        last_keepalive = asyncio.get_running_loop().time()

        while True:
            now = asyncio.get_running_loop().time()
            if now - last_keepalive >= _KEEPALIVE_SECONDS:
                yield ": keepalive\n\n"
                last_keepalive = now

            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message and message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                yield data

    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("SSE stream error for orgs %s", org_ids)
    finally:
        try:
            await pubsub.unsubscribe(*channels)
            await pubsub.close()
        except Exception:
            pass
        try:
            await r.aclose()
        except Exception:
            pass


@router.get("/signals", response_model=list[SSESignal])
async def get_sse_signals() -> list[SSESignal]:
    """Return all valid SSE signal types. Exposes SSESignal enum in OpenAPI for frontend codegen."""
    return list(SSESignal)


@router.get("/stream")
async def stream_events(
    session: SessionDep,
    current_user: CurrentUserSSE,
) -> StreamingResponse:
    """Stream real-time SSE events scoped to the authenticated user's organizations."""
    org_ids = [
        str(row)
        for row in session.exec(
            select(OrgMember.org_id).where(OrgMember.user_id == current_user.id)
        ).all()
    ]

    return StreamingResponse(
        _stream_events(org_ids),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
