"""WebSocket communication helpers for orchestrator.

Handles progress updates, logging, and bidirectional communication.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ...logging_config import get_logger

if TYPE_CHECKING:
    from .types import ExecutionState

logger = get_logger(__name__)


class WebSocketMixin:
    """Mixin providing WebSocket communication methods for OrchestratorService."""

    ws_task_id: str | None
    _state: ExecutionState
    _background_tasks: set[asyncio.Task[None]]
    _stop_handler_registered: bool
    _chat_handler_registered: bool
    _interrupted: bool
    _current_streaming_session_id: str | None
    _chat_messages: list[dict[str, object]]

    def _set_state(self, state: ExecutionState) -> None:
        """Update state and notify WebSocket if connected."""
        self._state = state
        logger.info("orchestrator_state_change", state=state.value, task_id=self.ws_task_id)

        if self.ws_task_id:
            task = asyncio.create_task(self._send_progress_update())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _send_progress_update(self) -> None:
        """Send progress update via WebSocket."""
        if not self.ws_task_id:
            return

        from ...api.ws_execution import send_progress

        await send_progress(
            self.ws_task_id,
            status=self._state.value,
        )

    async def _send_log(self, level: str, message: str, source: str = "orchestrator") -> None:
        """Send log message via WebSocket."""
        if not self.ws_task_id:
            return

        from ...api.ws_execution import send_log

        await send_log(self.ws_task_id, level, message, source)

    async def _send_model_change(self, model: str, reason: str = "") -> None:
        """Send model change notification via WebSocket."""
        if not self.ws_task_id:
            return

        from ...api.ws_execution import send_model_change

        await send_model_change(self.ws_task_id, model, reason)

    def register_stop_handler(self) -> None:
        """Register handler to receive stop signals from WebSocket."""
        if self._stop_handler_registered or not self.ws_task_id:
            return

        from ...api.ws_execution import register_stop_handler

        def handle_stop() -> None:
            logger.info("stop_signal_received", task_id=self.ws_task_id)
            self.receive_stop_signal()

        register_stop_handler(self.ws_task_id, handle_stop)
        self._stop_handler_registered = True

    def unregister_stop_handler(self) -> None:
        """Unregister stop signal handler."""
        if not self._stop_handler_registered or not self.ws_task_id:
            return

        from ...api.ws_execution import unregister_stop_handler

        unregister_stop_handler(self.ws_task_id)
        self._stop_handler_registered = False

    def register_chat_handler(self) -> None:
        """Register handler to receive chat messages from WebSocket."""
        if self._chat_handler_registered or not self.ws_task_id:
            return

        from ...api.ws_execution import register_chat_handler

        def handle_chat(message_data: dict[str, object]) -> None:
            logger.info("chat_message_received", task_id=self.ws_task_id)
            self.store_chat_message(message_data)

        register_chat_handler(self.ws_task_id, handle_chat)
        self._chat_handler_registered = True

    def unregister_chat_handler(self) -> None:
        """Unregister chat message handler."""
        if not self._chat_handler_registered or not self.ws_task_id:
            return

        from ...api.ws_execution import unregister_chat_handler

        unregister_chat_handler(self.ws_task_id)
        self._chat_handler_registered = False

    def receive_stop_signal(self) -> None:
        """Handle stop signal - interrupts current execution.

        Per decision d2: Uses dual interrupt mechanism:
        1. Set _interrupted flag for polling in _dispatch_to_worker
        2. Cancel active stream via Agent Hub registry (async)
        """
        self._interrupted = True
        logger.info("stop_signal_handled", task_id=self.ws_task_id, state=self._state.value)

        if self._current_streaming_session_id:
            task = asyncio.create_task(self._cancel_active_stream())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _cancel_active_stream(self) -> None:
        """Cancel active streaming session via Agent Hub REST API."""
        if not self._current_streaming_session_id:
            return

        from ..agent_hub_client import get_async_client

        try:
            async with get_async_client() as client:
                result = await client.cancel_stream(self._current_streaming_session_id)
                logger.info(
                    "stream_cancellation_result",
                    session_id=self._current_streaming_session_id,
                    result=result,
                )
        except Exception as e:
            logger.warning(
                "stream_cancellation_failed",
                session_id=self._current_streaming_session_id,
                error=str(e),
            )

    def store_chat_message(self, message: dict[str, object]) -> None:
        """Store chat message for resume context.

        Per decision d6: Chat messages stored in task.notes for resume.
        """
        self._chat_messages.append(
            {
                **message,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )


def create_stop_callback(callback: Callable[[], None]) -> Callable[[], None]:
    """Create a stop callback wrapper for external handlers."""
    return callback
