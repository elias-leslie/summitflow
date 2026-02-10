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

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..services.pubsub import subscribe_ws_events

# Re-export for backward compatibility
from .ws_execution_manager import (
    ConnectionManager,
    get_chat_handler,
    get_stop_handler,
    manager,
    register_chat_handler,
    register_stop_handler,
    unregister_chat_handler,
    unregister_stop_handler,
)
from .ws_execution_types import Message, MessageType

__all__ = [
    "ConnectionManager",
    "Message",
    "MessageType",
    "manager",
    "register_chat_handler",
    "register_stop_handler",
    "router",
    "send_error",
    "send_log",
    "send_model_change",
    "send_progress",
    "unregister_chat_handler",
    "unregister_stop_handler",
]

router = APIRouter()


async def _validate_task(websocket: WebSocket, task_id: str) -> bool:
    """Validate that the task exists. Returns True if valid, False if invalid (and closes connection)."""
    from ..storage import tasks as task_store

    task = task_store.get_task(task_id)
    if task:
        return True

    await websocket.accept()
    await websocket.send_json(
        Message(type=MessageType.ERROR, task_id=task_id, data={"error": f"Task not found: {task_id}", "recoverable": False}).to_dict()
    )
    await websocket.close(code=1008, reason=f"Task not found: {task_id}")
    return False


def _get_replay_sequence(websocket: WebSocket) -> int:
    """Extract replay sequence from query params."""
    if "from_sequence" not in websocket.query_params:
        return 0
    with contextlib.suppress(ValueError):
        return int(websocket.query_params["from_sequence"])
    return 0


async def _forward_redis_events(task_id: str) -> None:
    """Forward events from Redis to all connected clients via ConnectionManager."""
    async for event in subscribe_ws_events(task_id):
        try:
            msg_type_str = event.get("type", "log")
            msg_type = MessageType(msg_type_str) if msg_type_str in MessageType.__members__.values() else MessageType.LOG
            await manager.broadcast(task_id, Message(type=msg_type, task_id=task_id, data=event.get("data", {})))
        except Exception:
            break


async def _handle_stop_signal(task_id: str) -> None:
    """Handle stop signal from client."""
    handler = get_stop_handler(task_id)
    if handler:
        handler()
    await manager.broadcast(task_id, Message(type=MessageType.STOP_SIGNAL, task_id=task_id, data={"source": "user"}))


async def _handle_chat_message(task_id: str, message_data: dict[str, object]) -> None:
    """Handle chat message from client."""
    handler = get_chat_handler(task_id)
    if handler:
        handler(message_data)
    await manager.broadcast(task_id, Message(type=MessageType.CHAT_MESSAGE, task_id=task_id, data=message_data))


async def _process_client_message(task_id: str, data: dict[str, object]) -> None:
    """Process incoming message from client."""
    msg_type = data.get("type")
    if msg_type == MessageType.STOP_SIGNAL.value:
        await _handle_stop_signal(task_id)
    elif msg_type == MessageType.CHAT_MESSAGE.value:
        message_data = data.get("data", {})
        if isinstance(message_data, dict):
            await _handle_chat_message(task_id, message_data)


@router.websocket("/ws/execution/{task_id}")
async def websocket_execution(websocket: WebSocket, task_id: str) -> None:
    """WebSocket endpoint for execution streaming with reconnection support."""
    if not await _validate_task(websocket, task_id):
        return

    from_sequence = _get_replay_sequence(websocket)
    current_seq = await manager.connect(websocket, task_id)
    redis_task: asyncio.Task[None] | None = None

    try:
        await websocket.send_json(Message(type=MessageType.CONNECTED, task_id=task_id, data={"sequence": current_seq}).to_dict())
        if from_sequence > 0:
            await manager.replay(websocket, task_id, from_sequence)

        redis_task = asyncio.create_task(_forward_redis_events(task_id))

        while True:
            data = await websocket.receive_json()
            await _process_client_message(task_id, data)

    except WebSocketDisconnect:
        pass
    finally:
        if redis_task:
            redis_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await redis_task
        await manager.disconnect(websocket, task_id)


# Helper functions for orchestrator to send messages
async def send_log(task_id: str, level: str, message: str, source: str = "orchestrator") -> None:
    """Send a log message to all subscribers."""
    await manager.broadcast(
        task_id,
        Message(type=MessageType.LOG, task_id=task_id, data={"level": level, "message": message, "source": source}),
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
        task_id, Message(type=MessageType.MODEL_CHANGE, task_id=task_id, data={"model": model, "reason": reason})
    )


async def send_error(task_id: str, error: str, recoverable: bool = True) -> None:
    """Send an error message to all subscribers."""
    await manager.broadcast(
        task_id, Message(type=MessageType.ERROR, task_id=task_id, data={"error": error, "recoverable": recoverable})
    )
