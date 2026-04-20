"""Tests for autonomous work pickup task.

Covers:
- Guard checks (enabled, time window, concurrency)
- Task dispatching
- Dependency blocking
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch

from app.tasks.autonomous import autonomous_work_pickup


class TestGuardChecks:
    """Tests for guard condition enforcement via validate_autonomous_dispatch."""

    @patch(
        "app.tasks.autonomous.pickup.validate_autonomous_dispatch",
        return_value={"status": "disabled", "reason": "autonomous_enabled=false"},
    )
    def test_disabled_returns_disabled_status(self, mock_validate: MagicMock) -> None:
        """Test that disabled autonomous returns disabled status."""
        result = autonomous_work_pickup("test-project")

        assert result["status"] == "disabled"
        assert "autonomous_enabled" in cast(str, result["reason"])

    @patch(
        "app.tasks.autonomous.pickup.validate_autonomous_dispatch",
        return_value={
            "status": "outside_hours",
            "current_hour": 3,
            "start_hour": 9,
            "end_hour": 17,
        },
    )
    def test_outside_hours_returns_outside_hours_status(self, mock_validate: MagicMock) -> None:
        """Test that execution is skipped when outside configured hours."""
        result = autonomous_work_pickup("test-project")

        assert result["status"] == "outside_hours"
        assert "start_hour" in result
        assert "end_hour" in result

    @patch(
        "app.tasks.autonomous.pickup.validate_autonomous_dispatch",
        return_value={
            "status": "concurrency_limit",
            "running_count": 2,
            "max_concurrent": 2,
        },
    )
    def test_concurrency_limit_reached_returns_limit_status(
        self, mock_validate: MagicMock
    ) -> None:
        """Test that execution is skipped when at concurrency limit."""
        result = autonomous_work_pickup("test-project")

        assert result["status"] == "concurrency_limit"
        assert result["running_count"] == 2
        assert result["max_concurrent"] == 2


class TestTaskDispatching:
    """Tests for task dispatching to pipeline stages."""

    @patch("app.tasks.autonomous.pickup.validate_autonomous_dispatch", return_value=None)
    @patch("app.tasks.autonomous.pickup.get_queued_autonomous_tasks")
    @patch("app.tasks.autonomous.pickup._determine_next_stage")
    @patch("app.tasks.autonomous.pickup.validate_task_ready")
    @patch("app.tasks.autonomous.pickup.is_blocked", return_value=False)
    def test_task_dispatched_to_triage(
        self,
        mock_blocked: MagicMock,
        mock_validate_task_ready: MagicMock,
        mock_stage: MagicMock,
        mock_get_tasks: MagicMock,
        mock_validate: MagicMock,
    ) -> None:
        """Test that tasks needing triage are dispatched to triage."""
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
        mock_validate_task_ready.return_value = MagicMock(ready=True, issues=[], suggestions=[])

        mock_dispatch = MagicMock()
        result = autonomous_work_pickup("test-project", dispatch=mock_dispatch)

        mock_dispatch.assert_called_once_with("triage", "task-123", "test-project")
        assert result["dispatched"] == 1
        assert cast(dict[str, Any], result["breakdown"])["triage"] == 1

    @patch("app.tasks.autonomous.pickup.validate_autonomous_dispatch", return_value=None)
    @patch("app.tasks.autonomous.pickup.get_queued_autonomous_tasks")
    @patch("app.tasks.autonomous.pickup.validate_task_ready")
    def test_no_tasks_returns_zero_dispatched(
        self,
        mock_validate_task_ready: MagicMock,
        mock_get_tasks: MagicMock,
        mock_validate: MagicMock,
    ) -> None:
        """Test that empty queue returns zero dispatched."""
        mock_get_tasks.return_value = []

        result = autonomous_work_pickup("test-project")

        assert result["dispatched"] == 0
        assert result["message"] == "No pending autonomous tasks"

    @patch("app.tasks.autonomous.pickup.validate_autonomous_dispatch", return_value=None)
    @patch("app.tasks.autonomous.pickup.get_queued_autonomous_tasks")
    @patch("app.tasks.autonomous.pickup._determine_next_stage")
    @patch("app.tasks.autonomous.pickup.validate_task_ready")
    @patch("app.tasks.autonomous.pickup.is_blocked", return_value=True)
    def test_blocked_task_skipped(
        self,
        mock_blocked: MagicMock,
        mock_validate_task_ready: MagicMock,
        mock_stage: MagicMock,
        mock_get_tasks: MagicMock,
        mock_validate: MagicMock,
    ) -> None:
        """Test that blocked tasks are skipped during dispatch."""
        mock_get_tasks.return_value = [
            {
                "id": "task-blocked",
                "title": "Blocked task",
                "task_type": "feature",
                "status": "queue",
            }
        ]

        mock_dispatch = MagicMock()
        result = autonomous_work_pickup("test-project", dispatch=mock_dispatch)

        mock_dispatch.assert_not_called()
        mock_stage.assert_not_called()
        assert result["dispatched"] == 0
        assert result["attempted"] == 1
        assert cast(dict[str, Any], result["breakdown"])["skipped"] == 1

    @patch("app.tasks.autonomous.pickup.validate_autonomous_dispatch", return_value=None)
    @patch("app.tasks.autonomous.pickup.get_queued_autonomous_tasks")
    @patch("app.tasks.autonomous.pickup._determine_next_stage", return_value="execution")
    @patch("app.tasks.autonomous.pickup.validate_task_ready")
    @patch("app.tasks.autonomous.pickup.is_blocked", return_value=False)
    def test_execution_task_not_ready_is_skipped(
        self,
        _mock_blocked: MagicMock,
        mock_validate_task_ready: MagicMock,
        _mock_stage: MagicMock,
        mock_get_tasks: MagicMock,
        _mock_validate: MagicMock,
    ) -> None:
        mock_get_tasks.return_value = [
            {
                "id": "task-123",
                "title": "Add endpoint",
                "task_type": "feature",
                "complexity": "STANDARD",
                "status": "queue",
            }
        ]
        mock_validate_task_ready.return_value = MagicMock(
            ready=False,
            issues=["Missing done_when success criteria"],
            suggestions=["Re-run planning"],
        )

        mock_dispatch = MagicMock()
        result = autonomous_work_pickup("test-project", dispatch=mock_dispatch)

        mock_dispatch.assert_not_called()
        assert result["dispatched"] == 0
        assert result["attempted"] == 1
        assert cast(dict[str, Any], result["breakdown"])["skipped"] == 1

    @patch("app.tasks.autonomous.pickup.check_concurrency_limit")
    @patch("app.tasks.autonomous.pickup.dispatch_to_stage")
    @patch("app.tasks.autonomous.pickup.validate_autonomous_dispatch", return_value=None)
    @patch("app.tasks.autonomous.pickup.get_queued_autonomous_tasks")
    @patch("app.tasks.autonomous.pickup._determine_next_stage", return_value="execution")
    @patch("app.tasks.autonomous.pickup.validate_task_ready")
    @patch("app.tasks.autonomous.pickup.is_blocked", return_value=False)
    def test_batch_execution_rechecks_concurrency_between_tasks(
        self,
        _mock_blocked: MagicMock,
        mock_validate_task_ready: MagicMock,
        _mock_stage: MagicMock,
        mock_get_tasks: MagicMock,
        _mock_validate: MagicMock,
        mock_dispatch_to_stage: MagicMock,
        mock_check_concurrency_limit: MagicMock,
    ) -> None:
        mock_get_tasks.return_value = [
            {
                "id": "task-123",
                "title": "First execution task",
                "task_type": "feature",
                "complexity": "STANDARD",
                "status": "queue",
            },
            {
                "id": "task-456",
                "title": "Second execution task",
                "task_type": "feature",
                "complexity": "STANDARD",
                "status": "queue",
            },
        ]
        mock_validate_task_ready.return_value = MagicMock(ready=True, issues=[], suggestions=[])
        mock_dispatch_to_stage.return_value = True
        mock_check_concurrency_limit.side_effect = [
            None,
            {"status": "concurrency_limit", "running_count": 1, "max_concurrent": 1},
        ]

        mock_dispatch = MagicMock()
        result = autonomous_work_pickup("test-project", dispatch=mock_dispatch)

        mock_dispatch_to_stage.assert_called_once_with("execution", "task-123", "test-project", mock_dispatch)
        assert mock_check_concurrency_limit.call_count == 2
        assert result["dispatched"] == 1
        assert result["attempted"] == 2
        breakdown = cast(dict[str, Any], result["breakdown"])
        assert breakdown["execution"] == 1
        assert breakdown["skipped"] == 1
