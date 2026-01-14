"""Tests for OrchestratorService.

Covers:
- Task claiming and worktree setup
- Subtask execution with retry logic
- Failure handling and worktree revert
- WebSocket integration for progress updates
- Interrupt handling
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.constants import GEMINI_FLASH, GEMINI_PRO
from app.services.orchestrator import (
    ExecutionState,
    OrchestrationResult,
    OrchestratorService,
    SubtaskResult,
)


class TestOrchestratorService:
    """Tests for OrchestratorService class."""

    @pytest.fixture
    def mock_project_path(self, tmp_path: Path) -> Path:
        """Create a mock project path."""
        return tmp_path / "project"

    @pytest.fixture
    def orchestrator(self, mock_project_path: Path) -> OrchestratorService:
        """Create an OrchestratorService for testing."""
        with patch(
            "app.services.orchestrator.get_project_root_path", return_value=str(mock_project_path)
        ):
            return OrchestratorService("test-project", repo_path=mock_project_path)

    def test_init(self, orchestrator: OrchestratorService):
        """Test orchestrator initialization."""
        assert orchestrator.project_id == "test-project"
        assert orchestrator.state == ExecutionState.IDLE
        assert orchestrator._interrupted is False

    def test_state_changes(self, orchestrator: OrchestratorService):
        """Test state change tracking."""
        orchestrator._set_state(ExecutionState.CLAIMING)
        assert orchestrator.state == ExecutionState.CLAIMING

        orchestrator._set_state(ExecutionState.EXECUTING)
        assert orchestrator.state == ExecutionState.EXECUTING

    def test_receive_stop_signal(self, orchestrator: OrchestratorService):
        """Test stop signal handling."""
        assert orchestrator._interrupted is False
        orchestrator.receive_stop_signal()
        assert orchestrator._interrupted is True

    def test_store_chat_message(self, orchestrator: OrchestratorService):
        """Test chat message storage."""
        orchestrator.store_chat_message({"role": "user", "content": "Test message"})
        assert len(orchestrator._chat_messages) == 1
        assert orchestrator._chat_messages[0]["role"] == "user"
        assert "timestamp" in orchestrator._chat_messages[0]


class TestSubtaskResult:
    """Tests for SubtaskResult dataclass."""

    def test_default_values(self):
        """Test SubtaskResult default values."""
        result = SubtaskResult(subtask_id="1.1", success=True)
        assert result.subtask_id == "1.1"
        assert result.success is True
        assert result.error is None
        assert result.iterations == 0
        assert result.model_used == ""

    def test_with_error(self):
        """Test SubtaskResult with error."""
        result = SubtaskResult(
            subtask_id="1.1",
            success=False,
            error="Test error",
            iterations=3,
            model_used=GEMINI_FLASH,
        )
        assert result.success is False
        assert result.error == "Test error"
        assert result.iterations == 3
        assert result.model_used == GEMINI_FLASH


class TestOrchestrationResult:
    """Tests for OrchestrationResult dataclass."""

    def test_default_values(self):
        """Test OrchestrationResult default values."""
        result = OrchestrationResult(
            task_id="task-123",
            success=True,
            state=ExecutionState.COMPLETED,
        )
        assert result.task_id == "task-123"
        assert result.success is True
        assert result.state == ExecutionState.COMPLETED
        assert result.subtask_results == []
        assert result.error is None
        assert result.total_iterations == 0
        assert result.worktree_reverted is False

    def test_with_subtask_results(self):
        """Test OrchestrationResult with subtask results."""
        result = OrchestrationResult(
            task_id="task-123",
            success=True,
            state=ExecutionState.COMPLETED,
            subtask_results=[
                SubtaskResult(subtask_id="1.1", success=True, iterations=1),
                SubtaskResult(subtask_id="1.2", success=True, iterations=2),
            ],
            total_iterations=3,
        )
        assert len(result.subtask_results) == 2
        assert result.total_iterations == 3


class TestExecuteSubtask:
    """Tests for subtask execution logic."""

    @pytest.fixture
    def orchestrator(self, tmp_path: Path) -> OrchestratorService:
        """Create an OrchestratorService for testing."""
        with patch("app.services.orchestrator.get_project_root_path", return_value=str(tmp_path)):
            return OrchestratorService("test-project", repo_path=tmp_path)

    @pytest.mark.asyncio
    async def test_subtask_iteration_count(self, orchestrator: OrchestratorService):
        """Test that subtask tracks iteration count."""
        # Mock the dispatch to return failure
        with patch.object(
            orchestrator, "_dispatch_to_flash", new_callable=AsyncMock
        ) as mock_dispatch:
            mock_dispatch.return_value = (False, "Test failure")

            result = await orchestrator.execute_subtask(
                task_id="task-123",
                subtask={"id": "1.1", "description": "Test subtask"},
            )

            assert result.iterations == orchestrator.MAX_RETRIES
            assert result.success is False
            assert mock_dispatch.call_count == orchestrator.MAX_RETRIES

    @pytest.mark.asyncio
    async def test_subtask_model_escalation(self, orchestrator: OrchestratorService):
        """Test model escalation after stuck threshold."""
        models_used = []

        async def mock_dispatch(subtask: dict, model: str) -> tuple[bool, str | None]:
            models_used.append(model)
            return (False, "Test failure")

        with patch.object(orchestrator, "_dispatch_to_flash", side_effect=mock_dispatch):
            await orchestrator.execute_subtask(
                task_id="task-123",
                subtask={"id": "1.1", "description": "Test subtask"},
            )

            # First STUCK_THRESHOLD attempts use Flash
            for i in range(orchestrator.STUCK_THRESHOLD):
                assert models_used[i] == GEMINI_FLASH

            # After threshold, escalate to Pro
            for i in range(orchestrator.STUCK_THRESHOLD, len(models_used)):
                assert models_used[i] == GEMINI_PRO

    @pytest.mark.asyncio
    async def test_subtask_success_on_first_try(self, orchestrator: OrchestratorService):
        """Test successful subtask on first attempt."""
        # Create a mock worktree manager
        mock_wt_manager = MagicMock()
        mock_wt_manager.commit_in_worktree.return_value = True
        orchestrator._worktree_manager = mock_wt_manager

        with (
            patch.object(
                orchestrator, "_dispatch_to_flash", new_callable=AsyncMock
            ) as mock_dispatch,
            patch("app.services.orchestrator.update_subtask_passes") as mock_update,
        ):
            mock_dispatch.return_value = (True, None)
            orchestrator._current_worktree_path = Path("/tmp/test")

            result = await orchestrator.execute_subtask(
                task_id="task-123",
                subtask={"id": "1.1", "description": "Test subtask"},
            )

            assert result.success is True
            assert result.iterations == 1
            mock_update.assert_called_once()


class TestCoordinate:
    """Tests for full coordination flow."""

    @pytest.fixture
    def orchestrator(self, tmp_path: Path) -> OrchestratorService:
        """Create an OrchestratorService for testing."""
        with patch("app.services.orchestrator.get_project_root_path", return_value=str(tmp_path)):
            return OrchestratorService("test-project", repo_path=tmp_path)

    @pytest.mark.asyncio
    async def test_coordinate_claim_failure(self, orchestrator: OrchestratorService):
        """Test coordination when task claim fails."""
        with patch("app.services.orchestrator.task_store") as mock_store:
            mock_store.claim_task.return_value = None

            result = await orchestrator.coordinate("task-123")

            assert result.success is False
            assert result.state == ExecutionState.FAILED
            assert "claim" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_coordinate_no_subtasks(self, orchestrator: OrchestratorService):
        """Test coordination when task has no subtasks."""
        mock_worktree_info = MagicMock()
        mock_worktree_info.path = Path("/tmp/test")
        mock_worktree_info.branch = "exec/task-123"

        # Create a mock worktree manager before test
        mock_wt_manager = MagicMock()
        mock_wt_manager.create_worktree.return_value = mock_worktree_info
        orchestrator._worktree_manager = mock_wt_manager

        with (
            patch("app.services.orchestrator.task_store") as mock_store,
            patch("app.services.orchestrator.get_subtasks_for_task", return_value=[]),
        ):
            mock_store.claim_task.return_value = {"id": "task-123"}

            result = await orchestrator.coordinate("task-123")

            assert result.success is False
            assert "subtasks" in (result.error or "").lower()


class TestInterruptHandling:
    """Tests for interrupt handling."""

    @pytest.fixture
    def orchestrator(self, tmp_path: Path) -> OrchestratorService:
        """Create an OrchestratorService for testing."""
        with patch("app.services.orchestrator.get_project_root_path", return_value=str(tmp_path)):
            return OrchestratorService("test-project", repo_path=tmp_path, ws_task_id="task-123")

    @pytest.mark.asyncio
    async def test_execute_subtask_respects_interrupt(self, orchestrator: OrchestratorService):
        """Test that subtask execution respects interrupt flag."""
        orchestrator._interrupted = True

        result = await orchestrator.execute_subtask(
            task_id="task-123",
            subtask={"id": "1.1", "description": "Test"},
        )

        assert result.success is False
        assert result.error == "Interrupted"
        assert result.iterations == 0


class TestDispatchToFlash:
    """Tests for _dispatch_to_flash method using Agent Hub client."""

    @pytest.fixture
    def orchestrator(self, tmp_path: Path) -> OrchestratorService:
        """Create an OrchestratorService for testing."""
        with patch("app.services.orchestrator.get_project_root_path", return_value=str(tmp_path)):
            orch = OrchestratorService("test-project", repo_path=tmp_path)
            orch._current_worktree_path = tmp_path / "worktree"
            return orch

    @pytest.mark.asyncio
    async def test_dispatch_calls_agent_hub_run_agent(self, orchestrator: OrchestratorService):
        """Test that _dispatch_to_flash calls AsyncAgentHubClient.run_agent with correct params."""
        mock_result = MagicMock()
        mock_result.status = "success"
        mock_result.content = "DONE: Task completed"
        mock_result.progress_log = []
        mock_result.input_tokens = 100
        mock_result.output_tokens = 50
        mock_result.error = None

        mock_client = AsyncMock()
        mock_client.run_agent = AsyncMock(return_value=mock_result)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch("agent_hub.AsyncAgentHubClient", return_value=mock_client):
            success, error = await orchestrator._dispatch_to_flash(
                subtask={"id": "1.1", "description": "Test subtask", "steps": ["Step 1"]},
                model=GEMINI_FLASH,
            )

            assert success is True
            assert error is None
            mock_client.run_agent.assert_called_once()

            # Verify working_dir was passed
            call_kwargs = mock_client.run_agent.call_args.kwargs
            assert "working_dir" in call_kwargs
            assert call_kwargs["working_dir"] == str(orchestrator.effective_repo_path)

    @pytest.mark.asyncio
    async def test_dispatch_handles_agent_error(self, orchestrator: OrchestratorService):
        """Test that _dispatch_to_flash handles agent errors correctly."""
        mock_result = MagicMock()
        mock_result.status = "error"
        mock_result.content = ""
        mock_result.progress_log = []
        mock_result.error = "Agent failed"

        mock_client = AsyncMock()
        mock_client.run_agent = AsyncMock(return_value=mock_result)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch("agent_hub.AsyncAgentHubClient", return_value=mock_client):
            success, error = await orchestrator._dispatch_to_flash(
                subtask={"id": "1.1", "description": "Test"},
                model=GEMINI_FLASH,
            )

            assert success is False
            assert error == "Agent failed"


class TestWebSocketIntegration:
    """Tests for WebSocket integration."""

    @pytest.fixture
    def orchestrator(self, tmp_path: Path) -> OrchestratorService:
        """Create an OrchestratorService with ws_task_id."""
        with patch("app.services.orchestrator.get_project_root_path", return_value=str(tmp_path)):
            return OrchestratorService("test-project", repo_path=tmp_path, ws_task_id="task-123")

    def test_register_stop_handler(self, orchestrator: OrchestratorService):
        """Test stop handler registration."""
        with patch("app.api.ws_execution.register_stop_handler") as mock_register:
            orchestrator.register_stop_handler()
            mock_register.assert_called_once()
            assert orchestrator._stop_handler_registered is True

    def test_unregister_stop_handler(self, orchestrator: OrchestratorService):
        """Test stop handler unregistration."""
        orchestrator._stop_handler_registered = True

        with patch("app.api.ws_execution.unregister_stop_handler") as mock_unregister:
            orchestrator.unregister_stop_handler()
            mock_unregister.assert_called_once()
            assert orchestrator._stop_handler_registered is False

    @pytest.mark.asyncio
    async def test_send_log(self, orchestrator: OrchestratorService):
        """Test log message sending via WebSocket."""
        with patch("app.api.ws_execution.send_log", new_callable=AsyncMock) as mock_send:
            await orchestrator._send_log("info", "Test message")
            mock_send.assert_called_once_with("task-123", "info", "Test message", "orchestrator")

    @pytest.mark.asyncio
    async def test_send_model_change(self, orchestrator: OrchestratorService):
        """Test model change notification via WebSocket."""
        with patch("app.api.ws_execution.send_model_change", new_callable=AsyncMock) as mock_send:
            await orchestrator._send_model_change(GEMINI_PRO, "Stuck pattern")
            mock_send.assert_called_once_with("task-123", GEMINI_PRO, "Stuck pattern")

    @pytest.mark.asyncio
    async def test_handle_failure_sets_failed_status(self, tmp_path: Path):
        """Test that _handle_failure sets task status to 'failed' and does NOT release.

        This is a regression test for the bug where release_task was called after
        update_task_status("failed"), which reset the status back to "pending".
        """
        task_id = "test-failure-task"
        subtask_result = SubtaskResult(
            subtask_id="test-subtask",
            success=False,
            error="Test error message",
        )

        with (
            patch("app.services.orchestrator.get_project_root_path", return_value=str(tmp_path)),
            patch("app.services.orchestrator.get_worktree_manager") as mock_get_wt,
            patch("app.services.orchestrator.task_store") as mock_store,
        ):
            mock_wt = MagicMock()
            mock_wt.remove_worktree = MagicMock()
            mock_get_wt.return_value = mock_wt

            orchestrator = OrchestratorService(
                "test-project", repo_path=tmp_path, ws_task_id="task-123"
            )
            orchestrator._worktree_manager = mock_wt

            with patch.object(orchestrator, "_send_log", new_callable=AsyncMock):
                result = await orchestrator._handle_failure(task_id, subtask_result)

            # Should return True (revert succeeded)
            assert result is True

            # Should call update_task_status with "failed" and error_message
            mock_store.update_task_status.assert_called_once_with(
                task_id,
                "failed",
                error_message="Test error message",
            )

            # Should NOT call release_task (failed tasks stay failed)
            mock_store.release_task.assert_not_called()
