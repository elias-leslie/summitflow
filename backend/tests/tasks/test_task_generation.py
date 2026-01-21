"""Tests for task generation and cleanup Celery tasks.

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
    """Tests for generate_tasks_from_scan Celery task."""

    @patch("app.tasks.autonomous.task_generation.get_refactor_targets")
    def test_empty_targets_returns_zero_counts(self, mock_get_targets: MagicMock):
        """Test that empty targets returns zero counts."""
        mock_get_targets.return_value = {"targets": []}

        result = generate_tasks_from_scan("test-project")

        assert result["created_count"] == 0
        assert result["scanned_count"] == 0
        assert result["skipped_count"] == 0

    @patch("app.tasks.autonomous.task_generation.get_refactor_targets")
    @patch("app.tasks.autonomous.task_generation.task_store")
    @patch("app.tasks.autonomous.task_generation.qa_storage")
    @patch("app.tasks.autonomous.task_generation.link_issue_to_task")
    @patch("app.tasks.autonomous.task_generation.bulk_create_subtasks")
    @patch("app.tasks.autonomous.task_generation.bulk_create_steps")
    @patch("app.tasks.autonomous.task_generation.create_task_spirit")
    @patch("app.tasks.autonomous.task_generation.approve_plan")
    def test_creates_refactor_task_type(
        self,
        mock_approve: MagicMock,
        mock_spirit: MagicMock,
        mock_steps: MagicMock,
        mock_subtasks: MagicMock,
        mock_link: MagicMock,
        mock_qa: MagicMock,
        mock_store: MagicMock,
        mock_get_targets: MagicMock,
    ):
        """Test that created tasks have task_type='refactor'."""
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
        mock_qa.upsert_issue.return_value = "issue-123"
        mock_store.create_task.return_value = {"id": "task-123"}
        mock_subtasks.return_value = [{"id": "subtask-123"}]

        result = generate_tasks_from_scan("test-project")

        # Verify task was created with task_type='refactor'
        call_args = mock_store.create_task.call_args
        assert call_args is not None
        _, kwargs = call_args
        assert kwargs["task_type"] == "refactor"
        assert result["created_count"] == 1
        # Verify task_spirit was created
        mock_spirit.assert_called_once()
        mock_approve.assert_called_once()

    @patch("app.tasks.autonomous.task_generation.get_refactor_targets")
    @patch("app.tasks.autonomous.task_generation.task_store")
    def test_skips_existing_tasks(
        self,
        mock_store: MagicMock,
        mock_get_targets: MagicMock,
    ):
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
    """Tests for cleanup_stale_tasks Celery task."""

    @patch("app.storage.tasks.get_stale_tasks")
    def test_no_stale_tasks_returns_zero_counts(self, mock_get_stale: MagicMock):
        """Test that no stale tasks returns zero counts."""
        mock_get_stale.return_value = []

        result = cleanup_stale_tasks(max_age_days=30)

        assert result["cancelled_count"] == 0
        assert result["skipped_count"] == 0
        assert result["max_age_days"] == 30

    @patch("app.storage.tasks.get_stale_tasks")
    @patch("app.tasks.autonomous.task_generation.task_store")
    def test_cancels_stale_tasks(
        self,
        mock_store: MagicMock,
        mock_get_stale: MagicMock,
    ):
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
    @patch("app.tasks.autonomous.task_generation.task_store")
    def test_sets_cancelled_status_with_message(
        self,
        mock_store: MagicMock,
        mock_get_stale: MagicMock,
    ):
        """Test that cancelled tasks have proper status and message."""
        mock_get_stale.return_value = [
            {"id": "task-1", "title": "Stale task 1"},
        ]

        cleanup_stale_tasks(max_age_days=45)

        call_args = mock_store.update_task.call_args
        assert call_args is not None
        args, kwargs = call_args
        assert args[0] == "task-1"
        assert kwargs["status"] == "cancelled"
        assert "45+ days" in kwargs["progress_log"]

    @patch("app.storage.tasks.get_stale_tasks")
    @patch("app.tasks.autonomous.task_generation.task_store")
    def test_handles_update_errors(
        self,
        mock_store: MagicMock,
        mock_get_stale: MagicMock,
    ):
        """Test that update errors are handled gracefully."""
        mock_get_stale.return_value = [
            {"id": "task-1", "title": "Stale task 1"},
            {"id": "task-2", "title": "Stale task 2"},
        ]
        mock_store.update_task.side_effect = [None, Exception("DB error")]

        result = cleanup_stale_tasks(max_age_days=30)

        assert result["cancelled_count"] == 1
        assert result["skipped_count"] == 1
