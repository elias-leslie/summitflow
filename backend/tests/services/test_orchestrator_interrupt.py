"""Tests for OrchestratorService interrupt handling.

Covers:
- Stop signal reception and propagation
- Graceful cleanup on interrupt
- Chat message storage for resume context
- Resume from interrupt with context injection
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.orchestrator import (
    ExecutionState,
    OrchestrationResult,
    OrchestratorService,
)


class TestReceiveStopSignal:
    """Tests for receive_stop_signal method."""

    @pytest.fixture
    def orchestrator(self, tmp_path: Path) -> OrchestratorService:
        """Create an OrchestratorService for testing."""
        with patch("app.services.orchestrator.get_project_root_path", return_value=str(tmp_path)):
            return OrchestratorService("test-project", repo_path=tmp_path, ws_task_id="task-123")

    def test_sets_interrupted_flag(self, orchestrator: OrchestratorService):
        """Test that receive_stop_signal sets the interrupted flag."""
        assert orchestrator._interrupted is False
        orchestrator.receive_stop_signal()
        assert orchestrator._interrupted is True

    def test_logs_stop_signal(self, orchestrator: OrchestratorService):
        """Test that stop signal is logged."""
        with patch("app.services.orchestrator.logger") as mock_logger:
            orchestrator.receive_stop_signal()
            mock_logger.info.assert_called_with(
                "stop_signal_handled",
                task_id="task-123",
                state=ExecutionState.IDLE.value,
            )


class TestWebSocketStopSignalWiring:
    """Tests for WebSocket stop_signal integration."""

    @pytest.fixture
    def orchestrator(self, tmp_path: Path) -> OrchestratorService:
        """Create an OrchestratorService for testing."""
        with patch("app.services.orchestrator.get_project_root_path", return_value=str(tmp_path)):
            return OrchestratorService("test-project", repo_path=tmp_path, ws_task_id="task-123")

    def test_register_stop_handler_calls_receive_stop_signal(
        self, orchestrator: OrchestratorService
    ):
        """Test that registered handler calls receive_stop_signal."""
        captured_handler = None

        def capture_handler(task_id: str, handler: object) -> None:
            nonlocal captured_handler
            captured_handler = handler

        with patch("app.api.ws_execution.register_stop_handler", side_effect=capture_handler):
            orchestrator.register_stop_handler()

        # Verify handler was captured
        assert captured_handler is not None

        # Call the handler and verify it triggers receive_stop_signal
        with patch.object(orchestrator, "receive_stop_signal") as mock_receive:
            captured_handler()
            mock_receive.assert_called_once()


class TestGracefulCleanup:
    """Tests for graceful cleanup on interrupt."""

    @pytest.fixture
    def orchestrator(self, tmp_path: Path) -> OrchestratorService:
        """Create an OrchestratorService for testing."""
        with patch("app.services.orchestrator.get_project_root_path", return_value=str(tmp_path)):
            return OrchestratorService("test-project", repo_path=tmp_path, ws_task_id="task-123")

    @pytest.mark.asyncio
    async def test_handle_interruption_commits_partial_work(
        self, orchestrator: OrchestratorService
    ):
        """Test that interruption commits partial work."""
        mock_wt_manager = MagicMock()
        orchestrator._worktree_manager = mock_wt_manager
        orchestrator._current_worktree_path = Path("/tmp/test")

        result = OrchestrationResult(
            task_id="task-123",
            success=False,
            state=ExecutionState.INTERRUPTED,
        )

        with patch("app.services.orchestrator.task_store"):
            await orchestrator._handle_interruption("task-123", result)

            # Verify commit was attempted
            mock_wt_manager.commit_in_worktree.assert_called_once_with(
                "test-project", "task-123", "auto: Partial progress before interrupt"
            )

    @pytest.mark.asyncio
    async def test_handle_interruption_updates_task_status(self, orchestrator: OrchestratorService):
        """Test that interruption updates task status to paused."""
        mock_wt_manager = MagicMock()
        orchestrator._worktree_manager = mock_wt_manager

        result = OrchestrationResult(
            task_id="task-123",
            success=False,
            state=ExecutionState.INTERRUPTED,
        )

        with patch("app.services.orchestrator.task_store") as mock_store:
            await orchestrator._handle_interruption("task-123", result)

            # Verify task status updated to paused
            mock_store.update_task_status.assert_called_with("task-123", "paused")

    @pytest.mark.asyncio
    async def test_handle_interruption_releases_task(self, orchestrator: OrchestratorService):
        """Test that interruption releases the task lock."""
        mock_wt_manager = MagicMock()
        orchestrator._worktree_manager = mock_wt_manager

        result = OrchestrationResult(
            task_id="task-123",
            success=False,
            state=ExecutionState.INTERRUPTED,
        )

        with patch("app.services.orchestrator.task_store") as mock_store:
            await orchestrator._handle_interruption("task-123", result)

            # Verify task was released
            mock_store.release_task.assert_called_with("task-123")


class TestChatMessageStorage:
    """Tests for chat message storage for resume context."""

    @pytest.fixture
    def orchestrator(self, tmp_path: Path) -> OrchestratorService:
        """Create an OrchestratorService for testing."""
        with patch("app.services.orchestrator.get_project_root_path", return_value=str(tmp_path)):
            return OrchestratorService("test-project", repo_path=tmp_path)

    def test_store_chat_message_adds_timestamp(self, orchestrator: OrchestratorService):
        """Test that stored messages get timestamps."""
        orchestrator.store_chat_message({"role": "user", "content": "Test"})

        assert len(orchestrator._chat_messages) == 1
        assert "timestamp" in orchestrator._chat_messages[0]
        assert orchestrator._chat_messages[0]["role"] == "user"

    def test_store_multiple_chat_messages(self, orchestrator: OrchestratorService):
        """Test storing multiple chat messages."""
        orchestrator.store_chat_message({"role": "user", "content": "First"})
        orchestrator.store_chat_message({"role": "assistant", "content": "Second"})
        orchestrator.store_chat_message({"role": "user", "content": "Third"})

        assert len(orchestrator._chat_messages) == 3
        assert orchestrator._chat_messages[0]["content"] == "First"
        assert orchestrator._chat_messages[2]["content"] == "Third"

    @pytest.mark.asyncio
    async def test_chat_messages_saved_to_task_notes(self, orchestrator: OrchestratorService):
        """Test that chat messages are saved to task.notes on interrupt."""
        orchestrator.ws_task_id = "task-123"
        orchestrator.store_chat_message({"role": "user", "content": "Test direction"})

        mock_wt_manager = MagicMock()
        orchestrator._worktree_manager = mock_wt_manager

        result = OrchestrationResult(
            task_id="task-123",
            success=False,
            state=ExecutionState.INTERRUPTED,
        )

        with patch("app.services.orchestrator.task_store") as mock_store:
            await orchestrator._handle_interruption("task-123", result)

            # Verify task.notes was updated with chat context
            update_calls = mock_store.update_task.call_args_list
            assert any("CHAT_CONTEXT:" in str(call) for call in update_calls), (
                "Chat context should be saved to task notes"
            )


class TestResumeFromInterrupt:
    """Tests for resume_from_interrupt method."""

    @pytest.fixture
    def orchestrator(self, tmp_path: Path) -> OrchestratorService:
        """Create an OrchestratorService for testing."""
        with patch("app.services.orchestrator.get_project_root_path", return_value=str(tmp_path)):
            return OrchestratorService("test-project", repo_path=tmp_path)

    @pytest.mark.asyncio
    async def test_resume_task_not_found(self, orchestrator: OrchestratorService):
        """Test resume when task doesn't exist."""
        with patch("app.services.orchestrator.task_store") as mock_store:
            mock_store.get_task.return_value = None

            result = await orchestrator.resume_from_interrupt("task-nonexistent")

            assert result.success is False
            assert result.state == ExecutionState.FAILED
            assert "not found" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_resume_loads_chat_context(self, orchestrator: OrchestratorService):
        """Test that resume loads chat context from task notes."""
        mock_task = {
            "id": "task-123",
            "notes": "CHAT_CONTEXT:\n[{'role': 'user', 'content': 'Previous direction'}]",
        }

        with (
            patch("app.services.orchestrator.task_store") as mock_store,
            patch.object(orchestrator, "coordinate", new_callable=AsyncMock) as mock_coord,
        ):
            mock_store.get_task.return_value = mock_task
            mock_coord.return_value = OrchestrationResult(
                task_id="task-123",
                success=True,
                state=ExecutionState.COMPLETED,
            )

            await orchestrator.resume_from_interrupt("task-123")

            # Verify chat messages were loaded
            assert len(orchestrator._chat_messages) == 1
            assert orchestrator._chat_messages[0]["content"] == "Previous direction"

    @pytest.mark.asyncio
    async def test_resume_calls_coordinate(self, orchestrator: OrchestratorService):
        """Test that resume continues with coordinate."""
        mock_task = {"id": "task-123", "notes": ""}

        with (
            patch("app.services.orchestrator.task_store") as mock_store,
            patch.object(orchestrator, "coordinate", new_callable=AsyncMock) as mock_coord,
        ):
            mock_store.get_task.return_value = mock_task
            mock_coord.return_value = OrchestrationResult(
                task_id="task-123",
                success=True,
                state=ExecutionState.COMPLETED,
            )

            result = await orchestrator.resume_from_interrupt("task-123")

            mock_coord.assert_called_once_with("task-123")
            assert result.success is True


class TestInterruptDuringExecution:
    """Tests for interrupt handling during subtask execution."""

    @pytest.fixture
    def orchestrator(self, tmp_path: Path) -> OrchestratorService:
        """Create an OrchestratorService for testing."""
        with patch("app.services.orchestrator.get_project_root_path", return_value=str(tmp_path)):
            return OrchestratorService("test-project", repo_path=tmp_path, ws_task_id="task-123")

    @pytest.mark.asyncio
    async def test_subtask_stops_on_interrupt(self, orchestrator: OrchestratorService):
        """Test that subtask execution stops when interrupted."""
        orchestrator._interrupted = True

        result = await orchestrator.execute_subtask(
            task_id="task-123",
            subtask={"id": "1.1", "description": "Test subtask"},
        )

        assert result.success is False
        assert result.error == "Interrupted"
        assert result.iterations == 0

    @pytest.mark.asyncio
    async def test_interrupt_during_retry_loop(self, orchestrator: OrchestratorService):
        """Test interrupt during retry loop stops immediately."""
        call_count = 0

        async def mock_dispatch(subtask: dict, model: str) -> tuple[bool, str | None]:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                orchestrator._interrupted = True
            return (False, "Simulated failure")

        with patch.object(orchestrator, "_dispatch_to_flash", side_effect=mock_dispatch):
            result = await orchestrator.execute_subtask(
                task_id="task-123",
                subtask={"id": "1.1", "description": "Test subtask"},
            )

            # Should stop after interrupt, not complete all retries
            assert result.iterations < orchestrator.MAX_RETRIES
            assert result.error == "Interrupted"
