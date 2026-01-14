"""Tests for autonomous work pickup Celery task.

Covers:
- Time window checks
- Concurrency limit checks
- Task type filtering (refactor, debt, regression)
- OrchestratorService integration
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.execution import AUTONOMOUS_TASK_TYPES, autonomous_work_pickup


class TestAutonomousTaskTypes:
    """Tests for task type filtering."""

    def test_autonomous_task_types_includes_new_types(self):
        """Test that new task types are included."""
        assert "refactor" in AUTONOMOUS_TASK_TYPES
        assert "debt" in AUTONOMOUS_TASK_TYPES
        assert "regression" in AUTONOMOUS_TASK_TYPES

    def test_autonomous_task_types_includes_existing_types(self):
        """Test that existing task types are still included."""
        assert "task" in AUTONOMOUS_TASK_TYPES
        assert "bug" in AUTONOMOUS_TASK_TYPES
        assert "feature" in AUTONOMOUS_TASK_TYPES


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
    @patch("app.tasks.autonomous.execution.task_store")
    def test_within_hours_continues_execution(
        self,
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
        mock_store.list_ready_tasks.return_value = []

        result = autonomous_work_pickup("test-project")

        # Should get to "no_work" status (no tasks available)
        assert result["status"] == "no_work"


class TestConcurrencyLimitChecks:
    """Tests for concurrency limit enforcement."""

    @patch("app.storage.agent_configs.is_autonomous_enabled")
    @patch("app.storage.agent_configs.is_within_autonomous_hours")
    @patch("app.storage.agent_configs.get_autonomous_schedule")
    @patch("app.tasks.autonomous.execution.task_store")
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
    @patch("app.tasks.autonomous.execution.task_store")
    def test_under_concurrency_limit_continues_execution(
        self,
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
        mock_store.list_ready_tasks.return_value = []

        result = autonomous_work_pickup("test-project")

        # Should get to "no_work" status (no tasks available)
        assert result["status"] == "no_work"


class TestTaskTypeFiltering:
    """Tests for task type filtering in execution."""

    @patch("app.storage.agent_configs.is_autonomous_enabled")
    @patch("app.storage.agent_configs.is_within_autonomous_hours")
    @patch("app.storage.agent_configs.get_autonomous_schedule")
    @patch("app.tasks.autonomous.execution.task_store")
    @patch("app.tasks.autonomous.task_filters.check_exclusion")
    @patch("app.tasks.autonomous.execution.AUTONOMOUS_DRY_RUN", True)
    def test_refactor_task_is_picked_up(
        self,
        mock_exclusion: MagicMock,
        mock_store: MagicMock,
        mock_schedule: MagicMock,
        mock_within_hours: MagicMock,
        mock_enabled: MagicMock,
    ):
        """Test that refactor tasks are picked up for execution."""
        mock_enabled.return_value = True
        mock_within_hours.return_value = True
        mock_schedule.return_value = {
            "enabled": True,
            "start_hour": 0,
            "end_hour": 24,
            "max_concurrent": 1,
        }
        mock_store.count_running_tasks.return_value = 0
        mock_store.list_ready_tasks.return_value = [
            {
                "id": "task-123",
                "title": "Refactor: clean up module",
                "status": "pending",
                "tier": 2,
                "task_type": "refactor",
                "autonomous": True,  # Required for pickup
            }
        ]
        mock_exclusion.return_value = None

        result = autonomous_work_pickup("test-project")

        assert result["status"] == "dry_run"
        assert result["task_id"] == "task-123"
        assert result["task_type"] == "refactor"

    @patch("app.storage.agent_configs.is_autonomous_enabled")
    @patch("app.storage.agent_configs.is_within_autonomous_hours")
    @patch("app.storage.agent_configs.get_autonomous_schedule")
    @patch("app.tasks.autonomous.execution.task_store")
    def test_task_without_autonomous_flag_is_filtered(
        self,
        mock_store: MagicMock,
        mock_schedule: MagicMock,
        mock_within_hours: MagicMock,
        mock_enabled: MagicMock,
    ):
        """Test that tasks without autonomous=True are not picked up."""
        mock_enabled.return_value = True
        mock_within_hours.return_value = True
        mock_schedule.return_value = {
            "enabled": True,
            "start_hour": 0,
            "end_hour": 24,
            "max_concurrent": 1,
        }
        mock_store.count_running_tasks.return_value = 0
        mock_store.list_ready_tasks.return_value = [
            {
                "id": "task-123",
                "title": "Refactor: clean up module",
                "status": "pending",
                "tier": 2,
                "task_type": "refactor",
                "autonomous": False,  # Not enabled for autonomous
            }
        ]

        result = autonomous_work_pickup("test-project")

        # Should be filtered out even though task_type is valid
        assert result["status"] == "no_work"

    @patch("app.storage.agent_configs.is_autonomous_enabled")
    @patch("app.storage.agent_configs.is_within_autonomous_hours")
    @patch("app.storage.agent_configs.get_autonomous_schedule")
    @patch("app.tasks.autonomous.execution.task_store")
    def test_unknown_task_type_is_filtered_out(
        self,
        mock_store: MagicMock,
        mock_schedule: MagicMock,
        mock_within_hours: MagicMock,
        mock_enabled: MagicMock,
    ):
        """Test that unknown task types are not picked up."""
        mock_enabled.return_value = True
        mock_within_hours.return_value = True
        mock_schedule.return_value = {
            "enabled": True,
            "start_hour": 0,
            "end_hour": 24,
            "max_concurrent": 1,
        }
        mock_store.count_running_tasks.return_value = 0
        mock_store.list_ready_tasks.return_value = [
            {
                "id": "task-123",
                "title": "Unknown type task",
                "status": "pending",
                "tier": 2,
                "task_type": "unknown_type",  # Not in AUTONOMOUS_TASK_TYPES
            }
        ]

        result = autonomous_work_pickup("test-project")

        assert result["status"] == "no_work"


class TestDisabledAutonomous:
    """Tests for disabled autonomous execution."""

    @patch("app.storage.agent_configs.is_autonomous_enabled")
    def test_disabled_returns_disabled_status(self, mock_enabled: MagicMock):
        """Test that disabled autonomous returns disabled status."""
        mock_enabled.return_value = False

        result = autonomous_work_pickup("test-project")

        assert result["status"] == "disabled"
        assert "autonomous_enabled" in result["reason"]
