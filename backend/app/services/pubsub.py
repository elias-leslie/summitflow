"""Redis pub/sub for cross-process WebSocket messaging.

Enables Celery workers to publish messages that FastAPI WebSocket handlers receive.
This solves the process isolation problem: Celery workers can't directly access
FastAPI's in-memory ConnectionManager.

Usage:
    # In Celery worker (sync):
    publish_ws_event(task_id, {"type": "log", "data": {...}})

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

logger = get_logger(__name__)

WS_CHANNEL_PREFIX = "ws:execution:"


def get_channel_name(task_id: str) -> str:
    """Get Redis channel name for a task's WebSocket events."""
    return f"{WS_CHANNEL_PREFIX}{task_id}"


def publish_ws_event(task_id: str, event: dict[str, Any]) -> bool:
    """Publish a WebSocket event to Redis (sync, for Celery workers).

    Args:
        task_id: Task ID to publish to
        event: Event dict with type and data

    Returns:
        True if published successfully, False on error
    """
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
