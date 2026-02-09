"""Tests for autonomous work pickup task.

Covers:
- Time window checks
- Concurrency limit checks
- Task dispatching
- Disabled state handling
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous import autonomous_work_pickup


class TestTimeWindowChecks:
    """Tests for time window enforcement."""

    @patch("app.storage.agent_configs.is_autonomous_enabled")
    @patch("app.storage.agent_configs.is_within_autonomous_hours")
    @patch("app.storage.agent_configs.get_autonomous_schedule")
    def test_outside_hours_returns_outside_hours_status(
        self,
        mock_schedule: MagicMock,
        mock_within_hours: MagicMock,
        mock_enabled: MagicMock,
    ):
        """Test that execution is skipped when outside configured hours."""
        mock_enabled.return_value = True
        mock_within_hours.return_value = False
        mock_schedule.return_value = {
            "enabled": True,
            "start_hour": 9,
            "end_hour": 17,
            "max_concurrent": 1,
        }

        result = autonomous_work_pickup("test-project")

        assert result["status"] == "outside_hours"
        assert "start_hour" in result
        assert "end_hour" in result

    @patch("app.storage.agent_configs.is_autonomous_enabled")
    @patch("app.storage.agent_configs.is_within_autonomous_hours")
    @patch("app.storage.agent_configs.get_autonomous_schedule")
    @patch("app.tasks.autonomous.pickup.task_store")
    @patch("app.tasks.autonomous.pickup_queries.get_queued_autonomous_tasks")
    def test_within_hours_continues_execution(
        self,
        mock_get_tasks: MagicMock,
        mock_store: MagicMock,
        mock_schedule: MagicMock,
        mock_within_hours: MagicMock,
        mock_enabled: MagicMock,
    ):
        """Test that execution continues when within configured hours."""
        mock_enabled.return_value = True
        mock_within_hours.return_value = True
        mock_schedule.return_value = {
            "enabled": True,
            "start_hour": 0,
            "end_hour": 24,
            "max_concurrent": 1,
        }
        mock_store.count_running_tasks.return_value = 0
        mock_get_tasks.return_value = []

        result = autonomous_work_pickup("test-project")

        # Should return no tasks message (no tasks available)
        assert result["dispatched"] == 0
        assert result["message"] == "No tasks in queue"


class TestConcurrencyLimitChecks:
    """Tests for concurrency limit enforcement."""

    @patch("app.storage.agent_configs.is_autonomous_enabled")
    @patch("app.storage.agent_configs.is_within_autonomous_hours")
    @patch("app.storage.agent_configs.get_autonomous_schedule")
    @patch("app.tasks.autonomous.pickup.task_store")
    def test_concurrency_limit_reached_returns_limit_status(
        self,
        mock_store: MagicMock,
        mock_schedule: MagicMock,
        mock_within_hours: MagicMock,
        mock_enabled: MagicMock,
    ):
        """Test that execution is skipped when at concurrency limit."""
        mock_enabled.return_value = True
        mock_within_hours.return_value = True
        mock_schedule.return_value = {
            "enabled": True,
            "start_hour": 0,
            "end_hour": 24,
            "max_concurrent": 2,
        }
        mock_store.count_running_tasks.return_value = 2  # At limit

        result = autonomous_work_pickup("test-project")

        assert result["status"] == "concurrency_limit"
        assert result["running_count"] == 2
        assert result["max_concurrent"] == 2

    @patch("app.storage.agent_configs.is_autonomous_enabled")
    @patch("app.storage.agent_configs.is_within_autonomous_hours")
    @patch("app.storage.agent_configs.get_autonomous_schedule")
    @patch("app.tasks.autonomous.pickup.task_store")
    @patch("app.tasks.autonomous.pickup_queries.get_queued_autonomous_tasks")
    def test_under_concurrency_limit_continues_execution(
        self,
        mock_get_tasks: MagicMock,
        mock_store: MagicMock,
        mock_schedule: MagicMock,
        mock_within_hours: MagicMock,
        mock_enabled: MagicMock,
    ):
        """Test that execution continues when under concurrency limit."""
        mock_enabled.return_value = True
        mock_within_hours.return_value = True
        mock_schedule.return_value = {
            "enabled": True,
            "start_hour": 0,
            "end_hour": 24,
            "max_concurrent": 3,
        }
        mock_store.count_running_tasks.return_value = 1  # Under limit
        mock_get_tasks.return_value = []

        result = autonomous_work_pickup("test-project")

        # Should return no tasks message (no tasks available)
        assert result["dispatched"] == 0
        assert result["message"] == "No tasks in queue"


class TestTaskDispatching:
    """Tests for task dispatching to pipeline stages."""

    @patch("app.storage.agent_configs.is_autonomous_enabled")
    @patch("app.storage.agent_configs.is_within_autonomous_hours")
    @patch("app.storage.agent_configs.get_autonomous_schedule")
    @patch("app.tasks.autonomous.pickup.task_store")
    @patch("app.tasks.autonomous.pickup_queries.get_queued_autonomous_tasks")
    @patch("app.tasks.autonomous.pickup._determine_next_stage")
    def test_task_dispatched_to_triage(
        self,
        mock_stage: MagicMock,
        mock_get_tasks: MagicMock,
        mock_store: MagicMock,
        mock_schedule: MagicMock,
        mock_within_hours: MagicMock,
        mock_enabled: MagicMock,
    ):
        """Test that tasks needing triage are dispatched to triage."""
        mock_enabled.return_value = True
        mock_within_hours.return_value = True
        mock_schedule.return_value = {
            "enabled": True,
            "start_hour": 0,
            "end_hour": 24,
            "max_concurrent": 1,
        }
        mock_store.count_running_tasks.return_value = 0
        mock_get_tasks.return_value = [
            {
                "id": "task-123",
                "title": "Refactor: clean up module",
                "task_type": "refactor",
                "complexity": "low",
                "status": "queue",
            }
        ]
        mock_stage.return_value = "triage"

        mock_dispatch = MagicMock()
        result = autonomous_work_pickup("test-project", dispatch=mock_dispatch)

        mock_dispatch.assert_called_once_with("triage", "task-123", "test-project")
        assert result["dispatched"] == 1
        assert result["breakdown"]["triage"] == 1

    @patch("app.storage.agent_configs.is_autonomous_enabled")
    @patch("app.storage.agent_configs.is_within_autonomous_hours")
    @patch("app.storage.agent_configs.get_autonomous_schedule")
    @patch("app.tasks.autonomous.pickup.task_store")
    @patch("app.tasks.autonomous.pickup_queries.get_queued_autonomous_tasks")
    def test_no_tasks_returns_zero_dispatched(
        self,
        mock_get_tasks: MagicMock,
        mock_store: MagicMock,
        mock_schedule: MagicMock,
        mock_within_hours: MagicMock,
        mock_enabled: MagicMock,
    ):
        """Test that empty queue returns zero dispatched."""
        mock_enabled.return_value = True
        mock_within_hours.return_value = True
        mock_schedule.return_value = {
            "enabled": True,
            "start_hour": 0,
            "end_hour": 24,
            "max_concurrent": 1,
        }
        mock_store.count_running_tasks.return_value = 0
        mock_get_tasks.return_value = []

        result = autonomous_work_pickup("test-project")

        assert result["dispatched"] == 0
        assert result["message"] == "No tasks in queue"


class TestDisabledAutonomous:
    """Tests for disabled autonomous execution."""

    @patch("app.storage.agent_configs.is_autonomous_enabled")
    def test_disabled_returns_disabled_status(self, mock_enabled: MagicMock):
        """Test that disabled autonomous returns disabled status."""
        mock_enabled.return_value = False

        result = autonomous_work_pickup("test-project")

        assert result["status"] == "disabled"
        assert "autonomous_enabled" in result["reason"]
