"""WebSocket connection manager and handler registries.

Manages WebSocket connections, message broadcasting, and event handler
registration for execution streaming.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket

from .ws_execution_types import Message

if TYPE_CHECKING:
    from collections.abc import Callable


class ConnectionManager:
    """Manages WebSocket connections for execution streaming.

    Features:
    - Per-task subscriptions
    - Ephemeral Redis cache for instant reconnect (last 100 messages)
    - DB query for historical events on initial connect
    - Broadcast to all subscribers of a task
    """

    # Maximum messages to keep in ephemeral cache (performance optimization)
    MAX_REPLAY_MESSAGES = 100

    def __init__(self) -> None:
        # task_id -> list of WebSocket connections
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        # task_id -> ephemeral cache of recent messages (populated from live Redis stream)
        self._redis_cache: dict[str, list[Message]] = defaultdict(list)
        # task_id -> sequence counter
        self._sequences: dict[str, int] = defaultdict(int)
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, task_id: str) -> int:
        """Accept a WebSocket connection and subscribe to task updates.

        Returns the current sequence number for the task.
        """
        await websocket.accept()
        async with self._lock:
            self._connections[task_id].append(websocket)
            return self._sequences[task_id]

    async def disconnect(self, websocket: WebSocket, task_id: str) -> None:
        """Remove a WebSocket connection from subscriptions."""
        async with self._lock:
            if websocket in self._connections[task_id]:
                self._connections[task_id].remove(websocket)
            # Clean up empty lists
            if not self._connections[task_id]:
                del self._connections[task_id]

    async def broadcast(self, task_id: str, message: Message) -> None:
        """Send a message to all subscribers of a task."""
        async with self._lock:
            # Assign sequence number
            self._sequences[task_id] += 1
            message.sequence = self._sequences[task_id]

            # Add to ephemeral Redis cache (for instant reconnect)
            cache = self._redis_cache[task_id]
            cache.append(message)
            # Trim to max size
            if len(cache) > self.MAX_REPLAY_MESSAGES:
                self._redis_cache[task_id] = cache[-self.MAX_REPLAY_MESSAGES :]

        # Send to all connected clients
        connections = self._connections.get(task_id, [])
        disconnected = []
        for websocket in connections:
            try:
                await websocket.send_json(message.to_dict())
            except Exception:
                disconnected.append(websocket)

        # Clean up disconnected clients
        for ws in disconnected:
            await self.disconnect(ws, task_id)

    async def replay(
        self, websocket: WebSocket, task_id: str, from_sequence: int, trace_id: str | None = None
    ) -> None:
        """Replay missed messages to a reconnecting client.

        Historical events are loaded via HTTP (useTimelineHistory hook) to avoid
        duplicates. This method only replays from the ephemeral cache for very
        recent messages that may not yet be queryable via the API.

        Args:
            websocket: The WebSocket to send messages to
            task_id: The task to replay messages for
            from_sequence: Send messages after this sequence number
            trace_id: Trace ID (unused, kept for API compatibility)
        """
        async with self._lock:
            cache = self._redis_cache.get(task_id, [])
            messages_to_replay = [m for m in cache if m.sequence > from_sequence]

        for message in messages_to_replay:
            try:
                await websocket.send_json(message.to_dict())
            except Exception:
                break

    def get_connection_count(self, task_id: str) -> int:
        """Get the number of active connections for a task."""
        return len(self._connections.get(task_id, []))


# Global connection manager instance
manager = ConnectionManager()


# Callback registry for stop signals
_stop_handlers: dict[str, Callable[[], None]] = {}

# Callback registry for chat messages (receives dict with message data)
_chat_handlers: dict[str, Callable[[dict[str, Any]], None]] = {}


def register_stop_handler(task_id: str, handler: Callable[[], None]) -> None:
    """Register a callback to be invoked when a stop signal is received."""
    _stop_handlers[task_id] = handler


def unregister_stop_handler(task_id: str) -> None:
    """Unregister a stop handler for a task."""
    _stop_handlers.pop(task_id, None)


def register_chat_handler(task_id: str, handler: Callable[[dict[str, Any]], None]) -> None:
    """Register a callback to be invoked when a chat message is received.

    Args:
        task_id: Task ID to handle chat messages for
        handler: Callback that receives the message data dict
    """
    _chat_handlers[task_id] = handler


def unregister_chat_handler(task_id: str) -> None:
    """Unregister a chat handler for a task."""
    _chat_handlers.pop(task_id, None)


def get_stop_handler(task_id: str) -> Callable[[], None] | None:
    """Get the stop handler for a task, if registered."""
    return _stop_handlers.get(task_id)


def get_chat_handler(task_id: str) -> Callable[[dict[str, Any]], None] | None:
    """Get the chat handler for a task, if registered."""
    return _chat_handlers.get(task_id)
