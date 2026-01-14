"""WebSocket endpoint for execution streaming.

Provides real-time updates for autonomous task execution:
- Log messages from agents
- Progress updates (subtask/step completion)
- Model changes (switching between Sonnet/Flash/Pro)
- Chat messages for user direction
- Stop signals for immediate halt
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

if TYPE_CHECKING:
    from collections.abc import Callable

router = APIRouter()


class MessageType(str, Enum):
    """WebSocket message types."""

    LOG = "log"
    PROGRESS = "progress"
    MODEL_CHANGE = "model_change"
    CHAT_MESSAGE = "chat_message"
    STOP_SIGNAL = "stop_signal"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class Message:
    """A message in the execution stream."""

    type: MessageType
    task_id: str
    data: dict[str, object]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    sequence: int = 0

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.type.value,
            "task_id": self.task_id,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "sequence": self.sequence,
        }


class ConnectionManager:
    """Manages WebSocket connections for execution streaming.

    Features:
    - Per-task subscriptions
    - Message queue for replay on reconnection (last 100 messages)
    - Broadcast to all subscribers of a task
    """

    # Maximum messages to keep for replay
    MAX_REPLAY_MESSAGES = 100

    def __init__(self) -> None:
        # task_id -> list of WebSocket connections
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        # task_id -> list of recent messages for replay
        self._message_queues: dict[str, list[Message]] = defaultdict(list)
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

            # Add to replay queue
            queue = self._message_queues[task_id]
            queue.append(message)
            # Trim to max size
            if len(queue) > self.MAX_REPLAY_MESSAGES:
                self._message_queues[task_id] = queue[-self.MAX_REPLAY_MESSAGES :]

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

    async def replay(self, websocket: WebSocket, task_id: str, from_sequence: int) -> None:
        """Replay missed messages to a reconnecting client.

        Args:
            websocket: The WebSocket to send messages to
            task_id: The task to replay messages for
            from_sequence: Send messages after this sequence number
        """
        async with self._lock:
            queue = self._message_queues.get(task_id, [])
            messages_to_replay = [m for m in queue if m.sequence > from_sequence]

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


@router.websocket("/ws/execution/{task_id}")
async def websocket_execution(websocket: WebSocket, task_id: str) -> None:
    """WebSocket endpoint for execution streaming.

    Query params:
        from_sequence: Optional sequence number to replay from (for reconnection)

    Message format (incoming):
        {
            "type": "chat_message" | "stop_signal",
            "data": { ... }
        }

    Message format (outgoing):
        {
            "type": "log" | "progress" | "model_change" | "chat_message" | "connected" | "error",
            "task_id": "task-xxx",
            "data": { ... },
            "timestamp": "2024-01-13T...",
            "sequence": 123
        }
    """
    from ..storage import tasks as task_store

    # Validate task_id exists before accepting connection
    task = task_store.get_task(task_id)
    if not task:
        await websocket.accept()
        await websocket.send_json(
            Message(
                type=MessageType.ERROR,
                task_id=task_id,
                data={"error": f"Task not found: {task_id}", "recoverable": False},
            ).to_dict()
        )
        await websocket.close(code=1008, reason=f"Task not found: {task_id}")
        return

    # Get replay sequence from query params
    from_sequence = 0
    if "from_sequence" in websocket.query_params:
        with contextlib.suppress(ValueError):
            from_sequence = int(websocket.query_params["from_sequence"])

    # Accept connection
    current_seq = await manager.connect(websocket, task_id)

    try:
        # Send connection confirmation
        await websocket.send_json(
            Message(
                type=MessageType.CONNECTED,
                task_id=task_id,
                data={"sequence": current_seq},
            ).to_dict()
        )

        # Replay missed messages if reconnecting
        if from_sequence > 0:
            await manager.replay(websocket, task_id, from_sequence)

        # Listen for incoming messages
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == MessageType.STOP_SIGNAL.value:
                # Trigger stop handler if registered
                handler = _stop_handlers.get(task_id)
                if handler:
                    handler()
                # Broadcast stop signal to other listeners
                await manager.broadcast(
                    task_id,
                    Message(
                        type=MessageType.STOP_SIGNAL,
                        task_id=task_id,
                        data={"source": "user"},
                    ),
                )

            elif msg_type == MessageType.CHAT_MESSAGE.value:
                # Trigger chat handler if registered (for orchestrator)
                chat_handler = _chat_handlers.get(task_id)
                message_data = data.get("data", {})
                if chat_handler:
                    chat_handler(message_data)
                # Broadcast chat message to other listeners
                await manager.broadcast(
                    task_id,
                    Message(
                        type=MessageType.CHAT_MESSAGE,
                        task_id=task_id,
                        data=message_data,
                    ),
                )

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket, task_id)


# Helper functions for orchestrator to send messages
async def send_log(task_id: str, level: str, message: str, source: str = "orchestrator") -> None:
    """Send a log message to all subscribers."""
    await manager.broadcast(
        task_id,
        Message(
            type=MessageType.LOG,
            task_id=task_id,
            data={"level": level, "message": message, "source": source},
        ),
    )


async def send_progress(
    task_id: str,
    subtask_id: str | None = None,
    step: int | None = None,
    status: str = "in_progress",
    total_subtasks: int | None = None,
    completed_subtasks: int | None = None,
) -> None:
    """Send a progress update to all subscribers."""
    await manager.broadcast(
        task_id,
        Message(
            type=MessageType.PROGRESS,
            task_id=task_id,
            data={
                "subtask_id": subtask_id,
                "step": step,
                "status": status,
                "total_subtasks": total_subtasks,
                "completed_subtasks": completed_subtasks,
            },
        ),
    )


async def send_model_change(task_id: str, model: str, reason: str = "") -> None:
    """Send a model change notification to all subscribers."""
    await manager.broadcast(
        task_id,
        Message(
            type=MessageType.MODEL_CHANGE,
            task_id=task_id,
            data={"model": model, "reason": reason},
        ),
    )


async def send_error(task_id: str, error: str, recoverable: bool = True) -> None:
    """Send an error message to all subscribers."""
    await manager.broadcast(
        task_id,
        Message(
            type=MessageType.ERROR,
            task_id=task_id,
            data={"error": error, "recoverable": recoverable},
        ),
    )
