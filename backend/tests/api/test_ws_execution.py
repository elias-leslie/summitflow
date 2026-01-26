"""Tests for WebSocket execution streaming endpoint.

Covers:
- Connection establishment
- Message types
- Replay on reconnection
- Stop signal handling
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.api.ws_execution import (
    ConnectionManager,
    Message,
    MessageType,
    manager,
    register_stop_handler,
    send_error,
    send_log,
    send_model_change,
    send_progress,
    unregister_stop_handler,
)
from app.main import app


class TestMessageTypes:
    """Tests for message type enum and Message class."""

    def test_message_types_defined(self):
        """Test all required message types exist."""
        assert MessageType.LOG.value == "log"
        assert MessageType.PROGRESS.value == "progress"
        assert MessageType.MODEL_CHANGE.value == "model_change"
        assert MessageType.CHAT_MESSAGE.value == "chat_message"
        assert MessageType.STOP_SIGNAL.value == "stop_signal"
        assert MessageType.CONNECTED.value == "connected"
        assert MessageType.ERROR.value == "error"

    def test_message_to_dict(self):
        """Test Message serialization."""
        msg = Message(
            type=MessageType.LOG,
            task_id="task-123",
            data={"level": "info", "message": "test"},
        )
        result = msg.to_dict()
        assert result["type"] == "log"
        assert result["task_id"] == "task-123"
        assert result["data"]["level"] == "info"
        assert "timestamp" in result
        assert result["sequence"] == 0


class TestConnectionManager:
    """Tests for the ConnectionManager class."""

    @pytest.fixture
    def conn_manager(self):
        """Create a fresh ConnectionManager for each test."""
        return ConnectionManager()

    @pytest.mark.asyncio
    async def test_connection_count(self, conn_manager):
        """Test connection counting."""
        mock_ws = AsyncMock()
        await conn_manager.connect(mock_ws, "task-1")
        assert conn_manager.get_connection_count("task-1") == 1
        assert conn_manager.get_connection_count("task-2") == 0

    @pytest.mark.asyncio
    async def test_disconnect(self, conn_manager):
        """Test disconnection removes websocket."""
        mock_ws = AsyncMock()
        await conn_manager.connect(mock_ws, "task-1")
        assert conn_manager.get_connection_count("task-1") == 1

        await conn_manager.disconnect(mock_ws, "task-1")
        assert conn_manager.get_connection_count("task-1") == 0

    @pytest.mark.asyncio
    async def test_broadcast_assigns_sequence(self, conn_manager):
        """Test broadcast assigns incrementing sequence numbers."""
        mock_ws = AsyncMock()
        await conn_manager.connect(mock_ws, "task-1")

        msg1 = Message(type=MessageType.LOG, task_id="task-1", data={})
        await conn_manager.broadcast("task-1", msg1)
        assert msg1.sequence == 1

        msg2 = Message(type=MessageType.LOG, task_id="task-1", data={})
        await conn_manager.broadcast("task-1", msg2)
        assert msg2.sequence == 2

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self, conn_manager):
        """Test broadcast sends to all connected clients."""
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await conn_manager.connect(ws1, "task-1")
        await conn_manager.connect(ws2, "task-1")

        msg = Message(type=MessageType.LOG, task_id="task-1", data={"test": True})
        await conn_manager.broadcast("task-1", msg)

        ws1.send_json.assert_called_once()
        ws2.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_replay_sends_messages_after_sequence(self, conn_manager):
        """Test replay only sends messages after specified sequence."""
        mock_ws = AsyncMock()
        await conn_manager.connect(mock_ws, "task-1")

        # Broadcast 3 messages
        for i in range(3):
            msg = Message(type=MessageType.LOG, task_id="task-1", data={"i": i})
            await conn_manager.broadcast("task-1", msg)

        # New client reconnects
        replay_ws = AsyncMock()
        await conn_manager.replay(replay_ws, "task-1", from_sequence=1)

        # Should receive messages 2 and 3 (sequence > 1)
        assert replay_ws.send_json.call_count == 2

    @pytest.mark.asyncio
    async def test_redis_cache_limited(self, conn_manager):
        """Test Redis cache doesn't exceed MAX_REPLAY_MESSAGES."""
        mock_ws = AsyncMock()
        await conn_manager.connect(mock_ws, "task-1")

        # Broadcast more than max messages
        for i in range(conn_manager.MAX_REPLAY_MESSAGES + 50):
            msg = Message(type=MessageType.LOG, task_id="task-1", data={"i": i})
            await conn_manager.broadcast("task-1", msg)

        # Check cache is trimmed
        cache = conn_manager._redis_cache["task-1"]
        assert len(cache) == conn_manager.MAX_REPLAY_MESSAGES


class TestStopHandlers:
    """Tests for stop signal handler registration."""

    def test_register_and_unregister_handler(self):
        """Test stop handler registration and unregistration."""
        handler = lambda: None  # noqa: E731
        register_stop_handler("task-1", handler)
        # Handler should be registered (internal state)
        unregister_stop_handler("task-1")
        # Should not raise on unregister of non-existent
        unregister_stop_handler("task-nonexistent")


class TestHelperFunctions:
    """Tests for helper functions that send messages."""

    @pytest.mark.asyncio
    async def test_send_log(self):
        """Test send_log broadcasts correct message."""
        with patch.object(manager, "broadcast", new_callable=AsyncMock) as mock_broadcast:
            await send_log("task-1", "info", "Test message", source="test")
            mock_broadcast.assert_called_once()
            call_args = mock_broadcast.call_args[0]
            assert call_args[0] == "task-1"
            msg = call_args[1]
            assert msg.type == MessageType.LOG
            assert msg.data["level"] == "info"
            assert msg.data["message"] == "Test message"
            assert msg.data["source"] == "test"

    @pytest.mark.asyncio
    async def test_send_progress(self):
        """Test send_progress broadcasts correct message."""
        with patch.object(manager, "broadcast", new_callable=AsyncMock) as mock_broadcast:
            await send_progress(
                "task-1",
                subtask_id="1.1",
                step=2,
                status="completed",
                total_subtasks=5,
                completed_subtasks=2,
            )
            mock_broadcast.assert_called_once()
            msg = mock_broadcast.call_args[0][1]
            assert msg.type == MessageType.PROGRESS
            assert msg.data["subtask_id"] == "1.1"
            assert msg.data["step"] == 2
            assert msg.data["status"] == "completed"

    @pytest.mark.asyncio
    async def test_send_model_change(self):
        """Test send_model_change broadcasts correct message."""
        with patch.object(manager, "broadcast", new_callable=AsyncMock) as mock_broadcast:
            await send_model_change("task-1", "claude-sonnet-4-5", reason="Stuck pattern")
            mock_broadcast.assert_called_once()
            msg = mock_broadcast.call_args[0][1]
            assert msg.type == MessageType.MODEL_CHANGE
            assert msg.data["model"] == "claude-sonnet-4-5"
            assert msg.data["reason"] == "Stuck pattern"

    @pytest.mark.asyncio
    async def test_send_error(self):
        """Test send_error broadcasts correct message."""
        with patch.object(manager, "broadcast", new_callable=AsyncMock) as mock_broadcast:
            await send_error("task-1", "Something failed", recoverable=False)
            mock_broadcast.assert_called_once()
            msg = mock_broadcast.call_args[0][1]
            assert msg.type == MessageType.ERROR
            assert msg.data["error"] == "Something failed"
            assert msg.data["recoverable"] is False


class TestWebSocketEndpoint:
    """Tests for the WebSocket endpoint itself."""

    def test_websocket_route_exists(self):
        """Test that the WebSocket route is registered."""
        # Check routes in app
        routes = [r.path for r in app.routes]
        assert "/ws/execution/{task_id}" in routes

    @pytest.mark.asyncio
    async def test_websocket_validates_task_id(self):
        """Test that WebSocket sends error and closes for non-existent task."""
        from starlette.testclient import TestClient

        with patch("app.storage.tasks.get_task") as mock_get_task:
            mock_get_task.return_value = None  # Task not found

            client = TestClient(app)
            with client.websocket_connect("/ws/execution/nonexistent-task") as websocket:
                # Should receive error message before close
                data = websocket.receive_json()
                assert data["type"] == "error"
                assert "not found" in data["data"]["error"].lower()
                assert data["data"]["recoverable"] is False

            mock_get_task.assert_called_once_with("nonexistent-task")

    @pytest.mark.asyncio
    async def test_websocket_accepts_valid_task(self):
        """Test that WebSocket accepts connection for valid task."""
        from starlette.testclient import TestClient

        with patch("app.storage.tasks.get_task") as mock_get_task:
            mock_get_task.return_value = {"id": "task-123", "title": "Test"}

            client = TestClient(app)
            with client.websocket_connect("/ws/execution/task-123") as websocket:
                # Should receive connected message
                data = websocket.receive_json()
                assert data["type"] == "connected"
                assert data["task_id"] == "task-123"
