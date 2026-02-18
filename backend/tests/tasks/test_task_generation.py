"""Tests for task generation and cleanup tasks.

Covers:
- Refactor task generation from scans
- Stale task cleanup
- Task type settings (refactor vs task)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.task_generation import (
    cleanup_stale_tasks,
    generate_tasks_from_scan,
)


class TestGenerateTasksFromScan:
    """Tests for generate_tasks_from_scan task."""

    @patch("app.tasks.autonomous.refactor_generation.get_refactor_targets")
    def test_empty_targets_returns_zero_counts(self, mock_get_targets: MagicMock) -> None:
        """Test that empty targets returns zero counts."""
        mock_get_targets.return_value = {"targets": []}

        result = generate_tasks_from_scan("test-project")

        assert result["created_count"] == 0
        assert result["scanned_count"] == 0
        assert result["skipped_count"] == 0

    @patch("app.tasks.autonomous.refactor_generation.get_refactor_targets")
    @patch("app.tasks.autonomous.refactor_generation.task_store")
    @patch("app.tasks.autonomous.refactor_generation.create_refactor_task")
    def test_creates_refactor_task_type(
        self,
        mock_create_task: MagicMock,
        mock_store: MagicMock,
        mock_get_targets: MagicMock,
    ) -> None:
        """Test that refactor tasks are created from scan targets."""
        mock_get_targets.return_value = {
            "targets": [
                {
                    "path": "backend/app/services/foo.py",
                    "priority": "high",
                    "reason": "High cyclomatic complexity",
                    "complexity_score": 20.0,
                    "lines_of_code": 400,
                }
            ]
        }
        mock_store.task_exists_for_file.return_value = False
        mock_create_task.return_value = ("task-123", "issue-123")  # (task_id, issue_id)

        result = generate_tasks_from_scan("test-project")

        # Verify create_refactor_task was called
        mock_create_task.assert_called_once()
        # Verify task creation was counted
        assert result["created_count"] == 1

    @patch("app.tasks.autonomous.refactor_generation.get_refactor_targets")
    @patch("app.tasks.autonomous.refactor_generation.task_store")
    def test_skips_existing_tasks(
        self,
        mock_store: MagicMock,
        mock_get_targets: MagicMock,
    ) -> None:
        """Test that existing tasks are skipped."""
        mock_get_targets.return_value = {
            "targets": [
                {
                    "path": "backend/app/services/foo.py",
                    "priority": "medium",
                    "reason": "Complex method",
                    "complexity_score": 12.0,
                    "lines_of_code": 200,
                }
            ]
        }
        mock_store.task_exists_for_file.return_value = True

        result = generate_tasks_from_scan("test-project")

        assert result["created_count"] == 0
        assert result["scanned_count"] == 1
        assert result["skipped_count"] == 1
        mock_store.create_task.assert_not_called()


class TestCleanupStaleTasks:
    """Tests for cleanup_stale_tasks task."""

    @patch("app.storage.tasks.get_stale_tasks")
    def test_no_stale_tasks_returns_zero_counts(self, mock_get_stale: MagicMock) -> None:
        """Test that no stale tasks returns zero counts."""
        mock_get_stale.return_value = []

        result = cleanup_stale_tasks(max_age_days=30)

        assert result["cancelled_count"] == 0
        assert result["skipped_count"] == 0
        assert result["max_age_days"] == 30

    @patch("app.storage.tasks.get_stale_tasks")
    @patch("app.tasks.autonomous.cleanup_operations.task_store")
    def test_cancels_stale_tasks(
        self,
        mock_store: MagicMock,
        mock_get_stale: MagicMock,
    ) -> None:
        """Test that stale tasks are cancelled."""
        mock_get_stale.return_value = [
            {"id": "task-1", "title": "Stale task 1"},
            {"id": "task-2", "title": "Stale task 2"},
        ]

        result = cleanup_stale_tasks(max_age_days=30)

        assert result["cancelled_count"] == 2
        assert result["skipped_count"] == 0
        assert mock_store.update_task.call_count == 2

    @patch("app.storage.tasks.get_stale_tasks")
    @patch("app.tasks.autonomous.cleanup_operations.task_store")
    @patch("app.tasks.autonomous.cleanup_operations.log_task_event")
    def test_sets_cancelled_status_with_message(
        self,
        mock_log_event: MagicMock,
        mock_store: MagicMock,
        mock_get_stale: MagicMock,
    ) -> None:
        """Test that cancelled tasks have proper status and message."""
        mock_get_stale.return_value = [
            {"id": "task-1", "title": "Stale task 1"},
        ]

        cleanup_stale_tasks(max_age_days=45)

        # Verify update_task was called with cancelled status
        call_args = mock_store.update_task.call_args
        assert call_args is not None
        args, kwargs = call_args
        assert args[0] == "task-1"
        assert kwargs["status"] == "cancelled"

        # Verify log_task_event was called with the message
        mock_log_event.assert_called_once()
        event_args = mock_log_event.call_args
        assert event_args[0][0] == "task-1"
        assert "45+ days" in event_args[0][1]

    @patch("app.storage.tasks.get_stale_tasks")
    @patch("app.tasks.autonomous.cleanup_operations.task_store")
    def test_handles_update_errors(
        self,
        mock_store: MagicMock,
        mock_get_stale: MagicMock,
    ) -> None:
        """Test that update errors are handled gracefully."""
        mock_get_stale.return_value = [
            {"id": "task-1", "title": "Stale task 1"},
            {"id": "task-2", "title": "Stale task 2"},
        ]
        mock_store.update_task.side_effect = [None, Exception("DB error")]

        result = cleanup_stale_tasks(max_age_days=30)

        assert result["cancelled_count"] == 1
        assert result["skipped_count"] == 1
