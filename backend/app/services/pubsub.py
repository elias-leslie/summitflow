"""Redis pub/sub for cross-process WebSocket messaging.

Background workers publish messages that FastAPI WebSocket handlers receive,
solving process isolation: Hatchet workers can't access FastAPI's in-memory
ConnectionManager directly.

Events are persisted to PostgreSQL, then published to Redis for live streaming.
If Redis fails after DB write, the event is persisted but live clients may miss
it until reconnect (acceptable trade-off).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import redis
import redis.asyncio as aioredis

from ..config import REDIS_URL
from ..logging_config import get_logger
from ..storage.events import EventLevel, EventVisibility, create_event

logger = get_logger(__name__)

WS_CHANNEL_PREFIX = "ws:execution:"

# Module-level connection pools for reuse
_sync_pool: redis.ConnectionPool | None = None
_async_pool: aioredis.ConnectionPool | None = None


def _get_sync_pool() -> redis.ConnectionPool:
    """Get or create the synchronous Redis connection pool."""
    global _sync_pool
    if _sync_pool is None:
        _sync_pool = redis.ConnectionPool.from_url(REDIS_URL, max_connections=10)
    return _sync_pool


def _get_async_pool() -> aioredis.ConnectionPool:
    """Get or create the asynchronous Redis connection pool."""
    global _async_pool
    if _async_pool is None:
        _async_pool = aioredis.ConnectionPool.from_url(REDIS_URL, max_connections=10)
    return _async_pool


def get_channel_name(task_id: str) -> str:
    """Get Redis channel name for a task's WebSocket events."""
    return f"{WS_CHANNEL_PREFIX}{task_id}"


def _extract_event_fields(event: dict[str, object]) -> tuple[str, str | None, dict[str, object]]:
    """Extract event_type, message, and attributes from an event dict."""
    event_type = str(event.get("type", "log"))
    data = event.get("data")
    if not isinstance(data, dict):
        return event_type, None, {"raw": data}
    data_dict: dict[str, object] = {str(k): v for k, v in data.items()}
    message: str | None = str(data_dict["message"]) if "message" in data_dict else None
    return event_type, message, data_dict


def publish_ws_event(
    task_id: str,
    event: dict[str, object],
    *,
    project_id: str | None = None,
    trace_id: str | None = None,
    source: str = "worker",
    level: EventLevel = "info",
    visibility: EventVisibility = "user",
) -> bool:
    """Publish a WebSocket event to Redis (sync, for background workers).

    Persists event to PostgreSQL first, then publishes to Redis for live
    streaming. If Redis fails after DB write, event is still persisted.

    Returns True if published successfully, False on error.
    """
    if trace_id is None:
        trace_id = task_id

    if project_id is not None:
        event_type, message, attributes = _extract_event_fields(event)
        try:
            create_event(
                project_id=project_id,
                trace_id=trace_id,
                event_type=event_type,
                source=source,
                level=level,
                visibility=visibility,
                message=message,
                attributes=attributes,
            )
        except Exception as e:
            logger.warning("Failed to persist event to DB", task_id=task_id, error=str(e))

    try:
        r = redis.Redis(connection_pool=_get_sync_pool())
        r.publish(get_channel_name(task_id), json.dumps(event))
        return True
    except redis.RedisError as e:
        logger.warning("Failed to publish WebSocket event", task_id=task_id, error=str(e))
        return False


async def subscribe_ws_events(task_id: str) -> AsyncIterator[dict[str, object]]:
    """Subscribe to WebSocket events for a task (async, for FastAPI).

    Yields event dicts as they arrive. Exits when the client disconnects
    or the connection is closed.
    """
    pubsub: aioredis.client.PubSub | None = None
    channel = get_channel_name(task_id)

    try:
        pubsub = aioredis.Redis(connection_pool=_get_async_pool()).pubsub()
        await pubsub.subscribe(channel)
        logger.debug("Subscribed to Redis channel", channel=channel)

        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is not None and message["type"] == "message":
                try:
                    raw = message["data"]
                    yield json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    logger.warning("Failed to parse Redis message", error=str(e))
            await asyncio.sleep(0.01)

    except asyncio.CancelledError:
        logger.debug("Redis subscription cancelled", task_id=task_id)
        raise
    except Exception as e:
        logger.warning("Redis subscription error", task_id=task_id, error=str(e))
    finally:
        if pubsub:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
