"""Redis pub/sub for cross-process WebSocket messaging.

Enables Celery workers to publish messages that FastAPI WebSocket handlers receive.
This solves the process isolation problem: Celery workers can't directly access
FastAPI's in-memory ConnectionManager.

Events are persisted to PostgreSQL for historical queries, then published to Redis
for live streaming. If Redis fails after DB write, event is persisted but live
clients may miss it until reconnect (acceptable trade-off).

Usage:
    # In Celery worker (sync):
    publish_ws_event(task_id, {"type": "log", "data": {...}}, project_id="proj", trace_id="task-123")

    # In FastAPI WebSocket handler (async):
    async for message in subscribe_ws_events(task_id):
        await websocket.send_json(message)
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import redis
import redis.asyncio as aioredis

from ..config import REDIS_URL
from ..logging_config import get_logger
from ..storage.events import EventLevel, EventVisibility, create_event

logger = get_logger(__name__)

WS_CHANNEL_PREFIX = "ws:execution:"


def get_channel_name(task_id: str) -> str:
    """Get Redis channel name for a task's WebSocket events."""
    return f"{WS_CHANNEL_PREFIX}{task_id}"


def publish_ws_event(
    task_id: str,
    event: dict[str, Any],
    *,
    project_id: str | None = None,
    trace_id: str | None = None,
    source: str = "worker",
    level: EventLevel = "info",
    visibility: EventVisibility = "user",
) -> bool:
    """Publish a WebSocket event to Redis (sync, for Celery workers).

    Persists event to PostgreSQL first, then publishes to Redis for live streaming.
    If Redis fails after DB write, event is still persisted.

    Args:
        task_id: Task ID to publish to
        event: Event dict with type and data
        project_id: Project ID for DB persistence (required for persistence)
        trace_id: Trace ID for DB persistence (defaults to task_id)
        source: Event source (worker, orchestrator, agent, system)
        level: Log level (error, warning, info, debug)
        visibility: Visibility scope (user, internal, debug)

    Returns:
        True if published successfully, False on error
    """
    if trace_id is None:
        trace_id = task_id

    if project_id is not None:
        try:
            event_type = event.get("type", "log")
            message = (
                event.get("data", {}).get("message")
                if isinstance(event.get("data"), dict)
                else None
            )
            attributes = (
                event.get("data", {})
                if isinstance(event.get("data"), dict)
                else {"raw": event.get("data")}
            )

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
        r = redis.from_url(REDIS_URL)
        channel = get_channel_name(task_id)
        message = json.dumps(event)
        r.publish(channel, message)
        r.close()
        return True
    except redis.RedisError as e:
        logger.warning("Failed to publish WebSocket event", task_id=task_id, error=str(e))
        return False


async def subscribe_ws_events(task_id: str) -> AsyncIterator[dict[str, Any]]:
    """Subscribe to WebSocket events for a task (async, for FastAPI).

    Yields event dicts as they arrive. Exits when client disconnects
    or connection is closed.

    Args:
        task_id: Task ID to subscribe to

    Yields:
        Event dicts from the Redis channel
    """
    r: aioredis.Redis | None = None
    pubsub: aioredis.client.PubSub | None = None

    try:
        r = await aioredis.from_url(REDIS_URL)
        pubsub = r.pubsub()
        channel = get_channel_name(task_id)

        await pubsub.subscribe(channel)
        logger.debug("Subscribed to Redis channel", channel=channel)

        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is not None and message["type"] == "message":
                try:
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    event = json.loads(data)
                    yield event
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
            await pubsub.unsubscribe(get_channel_name(task_id))
            await pubsub.close()
        if r:
            await r.close()
