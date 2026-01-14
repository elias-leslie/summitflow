"""Integration tests for full orchestrator execution flow.

Covers:
- Create refactor task -> orchestrator picks up -> Flash executes subtasks -> Opus reviews
- Interrupt mid-execution -> task paused -> resume with chat context
- Failure after 3 retries -> worktree reverted -> task marked failed
- Time window respected (skip if outside hours)
- Concurrency limit respected
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.constants import GEMINI_FLASH, GEMINI_PRO
from app.services.orchestrator import (
    ExecutionState,
    OrchestrationResult,
    OrchestratorService,
)
from app.tasks.autonomous.execution import (
    AUTONOMOUS_TASK_TYPES,
    autonomous_work_pickup,
)

# Test fixtures


@pytest.fixture
def mock_project_path(tmp_path: Path) -> Path:
    """Create a mock project path."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    return project_dir


@pytest.fixture
def mock_subtasks() -> list[dict[str, Any]]:
    """Create mock subtasks for testing."""
    return [
        {
            "id": "sub-1",
            "subtask_full_id": "1.0",
            "description": "First subtask",
            "passes": False,
            "steps": [{"description": "Step 1", "passes": False}],
        },
        {
            "id": "sub-2",
            "subtask_full_id": "1.1",
            "description": "Second subtask",
            "passes": False,
            "steps": [{"description": "Step 1", "passes": False}],
        },
    ]


@pytest.fixture
def mock_worktree_info(tmp_path: Path) -> MagicMock:
    """Create mock worktree info."""
    info = MagicMock()
    info.path = tmp_path / "worktree"
    info.branch = "exec/task-123"
    return info


@pytest.fixture
def mock_task() -> dict[str, Any]:
    """Create a mock refactor task."""
    return {
        "id": "task-refactor-123",
        "title": "Refactor user authentication module",
        "task_type": "refactor",
        "tier": 2,
        "status": "pending",
        "project_id": "test-project",
    }


class TestRefactorTaskExecution:
    """Test: create refactor task -> orchestrator picks up -> Flash executes -> Opus reviews."""

    @pytest.mark.asyncio
    async def test_full_execution_flow_success(
        self,
        mock_project_path: Path,
        mock_subtasks: list[dict[str, Any]],
        mock_worktree_info: MagicMock,
    ):
        """Test complete execution flow with successful subtask completion."""
        with (
            patch(
                "app.services.orchestrator.get_project_root_path",
                return_value=str(mock_project_path),
            ),
            patch("app.services.orchestrator.task_store") as mock_store,
            patch("app.services.orchestrator.get_subtasks_for_task", return_value=mock_subtasks),
            patch("app.services.orchestrator.update_subtask_passes") as mock_update_subtask,
        ):
            # Setup mocks
            mock_store.claim_task.return_value = {"id": "task-123"}
            mock_store.update_task_status = MagicMock()
            mock_store.release_task = MagicMock()

            orchestrator = OrchestratorService("test-project", repo_path=mock_project_path)

            # Mock worktree manager
            mock_wt_manager = MagicMock()
            mock_wt_manager.create_worktree.return_value = mock_worktree_info
            mock_wt_manager.commit_in_worktree.return_value = True
            orchestrator._worktree_manager = mock_wt_manager

            # Mock Flash dispatch to succeed
            async def mock_dispatch(subtask: dict, model: str) -> tuple[bool, str | None]:
                return (True, None)

            with patch.object(orchestrator, "_dispatch_to_flash", side_effect=mock_dispatch):
                result = await orchestrator.coordinate("task-123")

            # Verify success
            assert result.success is True
            assert result.state == ExecutionState.COMPLETED
            assert len(result.subtask_results) == 2
            assert all(r.success for r in result.subtask_results)

            # Verify transitions through states
            mock_store.claim_task.assert_called_once()
            mock_wt_manager.create_worktree.assert_called_once()
            assert mock_update_subtask.call_count == 2  # Both subtasks marked passed

            # Verify Opus review transition
            mock_store.update_task_status.assert_called_with("task-123", "ai_reviewing")

    @pytest.mark.asyncio
    async def test_refactor_task_type_in_allowed_types(self):
        """Test that refactor task type is in allowed autonomous types."""
        assert "refactor" in AUTONOMOUS_TASK_TYPES
        assert "debt" in AUTONOMOUS_TASK_TYPES
        assert "regression" in AUTONOMOUS_TASK_TYPES

    @pytest.mark.asyncio
    async def test_flash_worker_used_for_subtasks(
        self, mock_project_path: Path, mock_worktree_info: MagicMock
    ):
        """Test that Flash model is used by default for subtask execution."""
        mock_subtasks = [
            {"id": "sub-1", "subtask_full_id": "1.0", "description": "Test", "passes": False}
        ]

        models_used = []

        async def track_model(subtask: dict, model: str) -> tuple[bool, str | None]:
            models_used.append(model)
            return (True, None)

        with (
            patch(
                "app.services.orchestrator.get_project_root_path",
                return_value=str(mock_project_path),
            ),
            patch("app.services.orchestrator.task_store") as mock_store,
            patch("app.services.orchestrator.get_subtasks_for_task", return_value=mock_subtasks),
            patch("app.services.orchestrator.update_subtask_passes"),
        ):
            mock_store.claim_task.return_value = {"id": "task-123"}

            orchestrator = OrchestratorService("test-project", repo_path=mock_project_path)

            mock_wt_manager = MagicMock()
            mock_wt_manager.create_worktree.return_value = mock_worktree_info
            mock_wt_manager.commit_in_worktree.return_value = True
            orchestrator._worktree_manager = mock_wt_manager

            with patch.object(orchestrator, "_dispatch_to_flash", side_effect=track_model):
                await orchestrator.coordinate("task-123")

            assert models_used[0] == GEMINI_FLASH


class TestInterruptAndResume:
    """Test: interrupt mid-execution -> task paused -> resume with chat context."""

    @pytest.mark.asyncio
    async def test_interrupt_pauses_task(
        self,
        mock_project_path: Path,
        mock_subtasks: list[dict[str, Any]],
        mock_worktree_info: MagicMock,
    ):
        """Test that interrupt signal pauses task and saves progress."""
        with (
            patch(
                "app.services.orchestrator.get_project_root_path",
                return_value=str(mock_project_path),
            ),
            patch("app.services.orchestrator.task_store") as mock_store,
            patch("app.services.orchestrator.get_subtasks_for_task", return_value=mock_subtasks),
        ):
            mock_store.claim_task.return_value = {"id": "task-123"}
            mock_store.update_task = MagicMock()
            mock_store.update_task_status = MagicMock()
            mock_store.release_task = MagicMock()

            orchestrator = OrchestratorService(
                "test-project", repo_path=mock_project_path, ws_task_id="task-123"
            )

            mock_wt_manager = MagicMock()
            mock_wt_manager.create_worktree.return_value = mock_worktree_info
            mock_wt_manager.commit_in_worktree.return_value = True
            orchestrator._worktree_manager = mock_wt_manager

            call_count = 0

            async def interrupt_after_first(subtask: dict, model: str) -> tuple[bool, str | None]:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # First subtask succeeds, then interrupt
                    orchestrator._interrupted = True
                    return (True, None)
                return (False, "Should not reach")

            with patch.object(
                orchestrator, "_dispatch_to_flash", side_effect=interrupt_after_first
            ):
                result = await orchestrator.coordinate("task-123")

            # Verify interrupted state
            assert result.state == ExecutionState.INTERRUPTED
            assert result.error is not None and "interrupt" in result.error.lower()

            # Verify task was paused
            mock_store.update_task_status.assert_called_with("task-123", "paused")
            mock_store.release_task.assert_called_with("task-123")

    @pytest.mark.asyncio
    async def test_chat_context_saved_on_interrupt(
        self, mock_project_path: Path, mock_worktree_info: MagicMock
    ):
        """Test that chat messages are saved to task notes on interrupt."""
        mock_subtasks = [
            {"id": "sub-1", "subtask_full_id": "1.0", "description": "Test", "passes": False}
        ]

        with (
            patch(
                "app.services.orchestrator.get_project_root_path",
                return_value=str(mock_project_path),
            ),
            patch("app.services.orchestrator.task_store") as mock_store,
            patch("app.services.orchestrator.get_subtasks_for_task", return_value=mock_subtasks),
        ):
            mock_store.claim_task.return_value = {"id": "task-123"}
            mock_store.update_task = MagicMock()
            mock_store.update_task_status = MagicMock()
            mock_store.release_task = MagicMock()

            orchestrator = OrchestratorService(
                "test-project", repo_path=mock_project_path, ws_task_id="task-123"
            )

            mock_wt_manager = MagicMock()
            mock_wt_manager.create_worktree.return_value = mock_worktree_info
            mock_wt_manager.commit_in_worktree.return_value = True
            orchestrator._worktree_manager = mock_wt_manager

            # Add chat messages
            orchestrator.store_chat_message({"role": "user", "content": "Focus on error handling"})
            orchestrator._interrupted = True

            async def fail_immediately(subtask: dict, model: str) -> tuple[bool, str | None]:
                return (False, "Interrupted")

            with patch.object(orchestrator, "_dispatch_to_flash", side_effect=fail_immediately):
                await orchestrator.coordinate("task-123")

            # Verify chat context saved
            update_calls = [str(call) for call in mock_store.update_task.call_args_list]
            assert any("CHAT_CONTEXT:" in call for call in update_calls)

    @pytest.mark.asyncio
    async def test_resume_loads_chat_context(self, mock_project_path: Path):
        """Test that resume loads chat context from task notes."""
        mock_task = {
            "id": "task-123",
            "notes": "CHAT_CONTEXT:\n[{'role': 'user', 'content': 'Previous direction', 'timestamp': '2025-01-01T00:00:00'}]",
        }

        with (
            patch(
                "app.services.orchestrator.get_project_root_path",
                return_value=str(mock_project_path),
            ),
            patch("app.services.orchestrator.task_store") as mock_store,
        ):
            mock_store.get_task.return_value = mock_task

            orchestrator = OrchestratorService("test-project", repo_path=mock_project_path)

            with patch.object(orchestrator, "coordinate", new_callable=AsyncMock) as mock_coord:
                mock_coord.return_value = OrchestrationResult(
                    task_id="task-123", success=True, state=ExecutionState.COMPLETED
                )

                await orchestrator.resume_from_interrupt("task-123")

                # Verify chat messages loaded
                assert len(orchestrator._chat_messages) == 1
                assert orchestrator._chat_messages[0]["content"] == "Previous direction"


class TestFailureAndRevert:
    """Test: failure after 3 retries -> worktree reverted -> task marked failed."""

    @pytest.mark.asyncio
    async def test_worktree_reverted_after_retries(
        self, mock_project_path: Path, mock_worktree_info: MagicMock
    ):
        """Test that worktree is reverted after exhausting retries."""
        mock_subtasks = [
            {"id": "sub-1", "subtask_full_id": "1.0", "description": "Test", "passes": False}
        ]

        with (
            patch(
                "app.services.orchestrator.get_project_root_path",
                return_value=str(mock_project_path),
            ),
            patch("app.services.orchestrator.task_store") as mock_store,
            patch("app.services.orchestrator.get_subtasks_for_task", return_value=mock_subtasks),
        ):
            mock_store.claim_task.return_value = {"id": "task-123"}
            mock_store.update_task_status = MagicMock()
            mock_store.release_task = MagicMock()

            orchestrator = OrchestratorService("test-project", repo_path=mock_project_path)

            mock_wt_manager = MagicMock()
            mock_wt_manager.create_worktree.return_value = mock_worktree_info
            mock_wt_manager.remove_worktree.return_value = None
            orchestrator._worktree_manager = mock_wt_manager

            async def always_fail(subtask: dict, model: str) -> tuple[bool, str | None]:
                return (False, "Simulated failure")

            with patch.object(orchestrator, "_dispatch_to_flash", side_effect=always_fail):
                result = await orchestrator.coordinate("task-123")

            # Verify failure state
            assert result.success is False
            assert result.state == ExecutionState.FAILED
            assert result.worktree_reverted is True

            # Verify worktree removed
            mock_wt_manager.remove_worktree.assert_called_once_with(
                "test-project", "task-123", delete_branch=True
            )

            # Verify task marked failed
            mock_store.update_task_status.assert_called_with(
                "task-123", "failed", error_message=result.subtask_results[0].error
            )

    @pytest.mark.asyncio
    async def test_max_retries_respected(
        self, mock_project_path: Path, mock_worktree_info: MagicMock
    ):
        """Test that exactly MAX_RETRIES attempts are made."""
        mock_subtasks = [
            {"id": "sub-1", "subtask_full_id": "1.0", "description": "Test", "passes": False}
        ]
        attempt_count = 0

        async def count_attempts(subtask: dict, model: str) -> tuple[bool, str | None]:
            nonlocal attempt_count
            attempt_count += 1
            return (False, "Failure")

        with (
            patch(
                "app.services.orchestrator.get_project_root_path",
                return_value=str(mock_project_path),
            ),
            patch("app.services.orchestrator.task_store") as mock_store,
            patch("app.services.orchestrator.get_subtasks_for_task", return_value=mock_subtasks),
        ):
            mock_store.claim_task.return_value = {"id": "task-123"}

            orchestrator = OrchestratorService("test-project", repo_path=mock_project_path)

            mock_wt_manager = MagicMock()
            mock_wt_manager.create_worktree.return_value = mock_worktree_info
            mock_wt_manager.remove_worktree.return_value = None
            orchestrator._worktree_manager = mock_wt_manager

            with patch.object(orchestrator, "_dispatch_to_flash", side_effect=count_attempts):
                result = await orchestrator.coordinate("task-123")

            assert attempt_count == orchestrator.MAX_RETRIES
            assert result.subtask_results[0].iterations == orchestrator.MAX_RETRIES

    @pytest.mark.asyncio
    async def test_model_escalation_to_pro(
        self, mock_project_path: Path, mock_worktree_info: MagicMock
    ):
        """Test model escalates to Pro after STUCK_THRESHOLD failures."""
        mock_subtasks = [
            {"id": "sub-1", "subtask_full_id": "1.0", "description": "Test", "passes": False}
        ]
        models_used = []

        async def track_model_failure(subtask: dict, model: str) -> tuple[bool, str | None]:
            models_used.append(model)
            return (False, "Failure")

        with (
            patch(
                "app.services.orchestrator.get_project_root_path",
                return_value=str(mock_project_path),
            ),
            patch("app.services.orchestrator.task_store") as mock_store,
            patch("app.services.orchestrator.get_subtasks_for_task", return_value=mock_subtasks),
        ):
            mock_store.claim_task.return_value = {"id": "task-123"}

            orchestrator = OrchestratorService("test-project", repo_path=mock_project_path)

            mock_wt_manager = MagicMock()
            mock_wt_manager.create_worktree.return_value = mock_worktree_info
            mock_wt_manager.remove_worktree.return_value = None
            orchestrator._worktree_manager = mock_wt_manager

            with patch.object(orchestrator, "_dispatch_to_flash", side_effect=track_model_failure):
                await orchestrator.coordinate("task-123")

            # Verify model escalation after STUCK_THRESHOLD
            for i in range(orchestrator.STUCK_THRESHOLD):
                assert models_used[i] == GEMINI_FLASH

            for i in range(orchestrator.STUCK_THRESHOLD, len(models_used)):
                assert models_used[i] == GEMINI_PRO


class TestTimeWindowRespected:
    """Test: time window respected (skip if outside hours)."""

    def test_outside_hours_skips_execution(self):
        """Test that autonomous pickup skips when outside time window."""
        with (
            patch("app.storage.agent_configs.is_autonomous_enabled", return_value=True),
            patch("app.storage.agent_configs.is_within_autonomous_hours", return_value=False),
            patch(
                "app.storage.agent_configs.get_autonomous_schedule",
                return_value={"start_hour": 9, "end_hour": 17, "max_concurrent": 1},
            ),
        ):
            result = autonomous_work_pickup("test-project")

            assert result["status"] == "outside_hours"
            assert "current_hour" in result
            assert "start_hour" in result
            assert "end_hour" in result

    def test_within_hours_proceeds(self):
        """Test that autonomous pickup proceeds when within time window."""
        mock_task = {
            "id": "task-123",
            "title": "Test task",
            "task_type": "refactor",
            "tier": 2,
            "status": "pending",
            "autonomous": True,  # Required for autonomous execution
        }

        with (
            patch("app.storage.agent_configs.is_autonomous_enabled", return_value=True),
            patch("app.storage.agent_configs.is_within_autonomous_hours", return_value=True),
            patch(
                "app.storage.agent_configs.get_autonomous_schedule",
                return_value={"start_hour": 0, "end_hour": 24, "max_concurrent": 1},
            ),
            patch("app.tasks.autonomous.execution.task_store") as mock_store,
            patch("app.tasks.autonomous.execution.check_exclusion", return_value=None),
            patch("app.tasks.autonomous.execution.get_project_repo_path", return_value="/tmp"),
            patch("app.services.orchestrator.OrchestratorService") as mock_orch,
        ):
            mock_store.count_running_tasks.return_value = 0
            mock_store.list_ready_tasks.return_value = [mock_task]

            # Mock orchestrator execution
            mock_instance = MagicMock()
            mock_orch.return_value = mock_instance

            async def mock_coordinate(task_id: str) -> OrchestrationResult:
                return OrchestrationResult(
                    task_id=task_id, success=True, state=ExecutionState.COMPLETED
                )

            mock_instance.coordinate = mock_coordinate

            result = autonomous_work_pickup("test-project")

            assert result["status"] == "success"
            assert result["task_id"] == "task-123"


class TestConcurrencyLimitRespected:
    """Test: concurrency limit respected."""

    def test_concurrency_limit_blocks_new_tasks(self):
        """Test that new tasks are blocked when at concurrency limit."""
        with (
            patch("app.storage.agent_configs.is_autonomous_enabled", return_value=True),
            patch("app.storage.agent_configs.is_within_autonomous_hours", return_value=True),
            patch(
                "app.storage.agent_configs.get_autonomous_schedule",
                return_value={"start_hour": 0, "end_hour": 24, "max_concurrent": 2},
            ),
            patch("app.tasks.autonomous.execution.task_store") as mock_store,
        ):
            mock_store.count_running_tasks.return_value = 2  # At limit

            result = autonomous_work_pickup("test-project")

            assert result["status"] == "concurrency_limit"
            assert result["running_count"] == 2
            assert result["max_concurrent"] == 2

    def test_under_concurrency_limit_proceeds(self):
        """Test that tasks proceed when under concurrency limit."""
        mock_task = {
            "id": "task-123",
            "title": "Test task",
            "task_type": "debt",
            "tier": 2,
            "status": "pending",
            "autonomous": True,  # Required for autonomous execution
        }

        with (
            patch("app.storage.agent_configs.is_autonomous_enabled", return_value=True),
            patch("app.storage.agent_configs.is_within_autonomous_hours", return_value=True),
            patch(
                "app.storage.agent_configs.get_autonomous_schedule",
                return_value={"start_hour": 0, "end_hour": 24, "max_concurrent": 3},
            ),
            patch("app.tasks.autonomous.execution.task_store") as mock_store,
            patch("app.tasks.autonomous.execution.check_exclusion", return_value=None),
            patch("app.tasks.autonomous.execution.get_project_repo_path", return_value="/tmp"),
            patch("app.services.orchestrator.OrchestratorService") as mock_orch,
        ):
            mock_store.count_running_tasks.return_value = 1  # Under limit
            mock_store.list_ready_tasks.return_value = [mock_task]

            mock_instance = MagicMock()
            mock_orch.return_value = mock_instance

            async def mock_coordinate(task_id: str) -> OrchestrationResult:
                return OrchestrationResult(
                    task_id=task_id, success=True, state=ExecutionState.COMPLETED
                )

            mock_instance.coordinate = mock_coordinate

            result = autonomous_work_pickup("test-project")

            assert result["status"] == "success"


class TestAutonomousDisabled:
    """Test: autonomous disabled returns early."""

    def test_disabled_returns_early(self):
        """Test that disabled autonomous returns immediately."""
        with patch("app.storage.agent_configs.is_autonomous_enabled", return_value=False):
            result = autonomous_work_pickup("test-project")

            assert result["status"] == "disabled"
            assert result["reason"] == "autonomous_enabled=false"


class TestTaskTypeFiltering:
    """Test: task type filtering for autonomous execution."""

    def test_only_allowed_task_types_picked(self):
        """Test that only allowed task types are picked for execution."""
        tasks = [
            {
                "id": "t1",
                "task_type": "refactor",
                "tier": 2,
                "status": "pending",
                "autonomous": True,
            },
            {
                "id": "t2",
                "task_type": "feature",
                "tier": 2,
                "status": "pending",
                "autonomous": True,
            },
            {
                "id": "t3",
                "task_type": "unknown",
                "tier": 2,
                "status": "pending",
                "autonomous": True,
            },  # Not allowed (type)
        ]

        with (
            patch("app.storage.agent_configs.is_autonomous_enabled", return_value=True),
            patch("app.storage.agent_configs.is_within_autonomous_hours", return_value=True),
            patch(
                "app.storage.agent_configs.get_autonomous_schedule",
                return_value={"start_hour": 0, "end_hour": 24, "max_concurrent": 1},
            ),
            patch("app.tasks.autonomous.execution.task_store") as mock_store,
            patch("app.tasks.autonomous.execution.check_exclusion", return_value=None),
            patch("app.tasks.autonomous.execution.get_project_repo_path", return_value="/tmp"),
            patch("app.services.orchestrator.OrchestratorService") as mock_orch,
        ):
            mock_store.count_running_tasks.return_value = 0
            mock_store.list_ready_tasks.return_value = tasks

            mock_instance = MagicMock()
            mock_orch.return_value = mock_instance

            async def mock_coordinate(task_id: str) -> OrchestrationResult:
                return OrchestrationResult(
                    task_id=task_id, success=True, state=ExecutionState.COMPLETED
                )

            mock_instance.coordinate = mock_coordinate

            result = autonomous_work_pickup("test-project")

            # First matching task should be picked
            assert result["status"] == "success"
            assert result["task_id"] == "t1"
