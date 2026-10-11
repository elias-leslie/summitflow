"""Stale auto-generated task archiving."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.stale_generated_tasks import cleanup_stale_tasks


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
    @patch("app.tasks.stale_generated_tasks.close_obsolete_generated_task")
    def test_cancels_stale_tasks(
        self,
        mock_close: MagicMock,
        mock_get_stale: MagicMock,
    ) -> None:
        """Test that stale tasks are cancelled."""
        mock_close.side_effect = ["deleted", "cancelled"]
        mock_get_stale.return_value = [
            {"id": "task-1", "title": "Stale task 1"},
            {"id": "task-2", "title": "Stale task 2"},
        ]

        result = cleanup_stale_tasks(max_age_days=30)

        assert result["cancelled_count"] == 2
        assert result["skipped_count"] == 0
        assert mock_close.call_count == 2

    @patch("app.storage.tasks.get_stale_tasks")
    @patch("app.tasks.stale_generated_tasks.close_obsolete_generated_task")
    @patch("app.tasks.stale_generated_tasks.log_task_event")
    def test_sets_cancelled_status_with_message(
        self,
        mock_log_event: MagicMock,
        mock_close: MagicMock,
        mock_get_stale: MagicMock,
    ) -> None:
        """Test that cancelled tasks have proper status and message."""
        mock_close.return_value = "cancelled"
        mock_get_stale.return_value = [
            {"id": "task-1", "title": "Stale task 1"},
        ]

        cleanup_stale_tasks(max_age_days=45)

        mock_close.assert_called_once()

        # Verify log_task_event was called with the message
        mock_log_event.assert_called_once()
        event_args = mock_log_event.call_args
        assert event_args[0][0] == "task-1"
        assert "45+ days" in event_args[0][1]

    @patch("app.storage.tasks.get_stale_tasks")
    @patch("app.tasks.stale_generated_tasks.close_obsolete_generated_task")
    def test_handles_update_errors(
        self,
        mock_close: MagicMock,
        mock_get_stale: MagicMock,
    ) -> None:
        """Test that update errors are handled gracefully."""
        mock_get_stale.return_value = [
            {"id": "task-1", "title": "Stale task 1"},
            {"id": "task-2", "title": "Stale task 2"},
        ]
        mock_close.side_effect = ["cancelled", Exception("DB error")]

        result = cleanup_stale_tasks(max_age_days=30)

        assert result["cancelled_count"] == 1
        assert result["skipped_count"] == 1
