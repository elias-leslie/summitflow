"""Unit tests for self-healing Celery tasks.

Tests the scheduled monitoring task and rate limiting.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from app.services.self_healing.monitor import PRIORITY_ERR, JournalError
from app.tasks.self_healing import (
    MAX_TASKS_PER_RUN,
    monitor_systemd_errors,
)


class TestMonitorSystemdErrors:
    """Tests for the monitor_systemd_errors Celery task."""

    @patch("app.tasks.self_healing.create_error_task")
    @patch("app.tasks.self_healing.SystemdMonitor")
    def test_no_errors_returns_zero_counts(
        self,
        mock_monitor_cls: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """No errors results in zero counts."""
        mock_monitor = MagicMock()
        mock_monitor.get_new_errors.return_value = []
        mock_monitor_cls.return_value = mock_monitor

        result = monitor_systemd_errors()

        assert result == {"created": 0, "skipped": 0, "errors": 0}
        mock_create.assert_not_called()

    @patch("app.tasks.self_healing.create_error_task")
    @patch("app.tasks.self_healing.SystemdMonitor")
    def test_creates_tasks_for_new_errors(
        self,
        mock_monitor_cls: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Creates tasks for detected errors."""
        mock_monitor = MagicMock()
        mock_monitor.get_new_errors.return_value = [
            JournalError(
                unit="test.service",
                message="Error 1",
                priority=PRIORITY_ERR,
                timestamp=datetime.now(UTC),
                error_hash="hash1",
            ),
            JournalError(
                unit="test.service",
                message="Error 2",
                priority=PRIORITY_ERR,
                timestamp=datetime.now(UTC),
                error_hash="hash2",
            ),
        ]
        mock_monitor_cls.return_value = mock_monitor
        mock_create.return_value = {"id": "task-123"}

        result = monitor_systemd_errors(project_id="test-project")

        assert result["created"] == 2
        assert result["skipped"] == 0
        assert result["errors"] == 0
        assert mock_create.call_count == 2

    @patch("app.tasks.self_healing.create_error_task")
    @patch("app.tasks.self_healing.SystemdMonitor")
    def test_counts_skipped_duplicates(
        self,
        mock_monitor_cls: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Skipped duplicates are counted."""
        mock_monitor = MagicMock()
        mock_monitor.get_new_errors.return_value = [
            JournalError(
                unit="test.service",
                message="Error",
                priority=PRIORITY_ERR,
                timestamp=datetime.now(UTC),
                error_hash="hash1",
            ),
        ]
        mock_monitor_cls.return_value = mock_monitor
        mock_create.return_value = None  # Duplicate

        result = monitor_systemd_errors()

        assert result["created"] == 0
        assert result["skipped"] == 1

    @patch("app.tasks.self_healing.create_error_task")
    @patch("app.tasks.self_healing.SystemdMonitor")
    def test_counts_creation_errors(
        self,
        mock_monitor_cls: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Task creation errors are counted."""
        mock_monitor = MagicMock()
        mock_monitor.get_new_errors.return_value = [
            JournalError(
                unit="test.service",
                message="Error",
                priority=PRIORITY_ERR,
                timestamp=datetime.now(UTC),
                error_hash="hash1",
            ),
        ]
        mock_monitor_cls.return_value = mock_monitor
        mock_create.side_effect = Exception("DB error")

        result = monitor_systemd_errors()

        assert result["created"] == 0
        assert result["errors"] == 1

    @patch("app.tasks.self_healing.create_error_task")
    @patch("app.tasks.self_healing.SystemdMonitor")
    def test_rate_limiting(
        self,
        mock_monitor_cls: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Rate limits task creation to max_tasks."""
        errors = [
            JournalError(
                unit="test.service",
                message=f"Error {i}",
                priority=PRIORITY_ERR,
                timestamp=datetime.now(UTC),
                error_hash=f"hash{i}",
            )
            for i in range(15)  # More than default limit
        ]
        mock_monitor = MagicMock()
        mock_monitor.get_new_errors.return_value = errors
        mock_monitor_cls.return_value = mock_monitor
        mock_create.return_value = {"id": "task-123"}

        result = monitor_systemd_errors(max_tasks=5)

        # Only 5 tasks created due to rate limit
        assert result["created"] == 5
        assert mock_create.call_count == 5

    @patch("app.tasks.self_healing.create_error_task")
    @patch("app.tasks.self_healing.SystemdMonitor")
    def test_uses_custom_since_parameter(
        self,
        mock_monitor_cls: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Custom since parameter is passed to monitor."""
        mock_monitor = MagicMock()
        mock_monitor.get_new_errors.return_value = []
        mock_monitor_cls.return_value = mock_monitor

        monitor_systemd_errors(since="10 minutes ago")

        mock_monitor_cls.assert_called_once_with(since="10 minutes ago")

    @patch("app.tasks.self_healing.create_error_task")
    @patch("app.tasks.self_healing.SystemdMonitor")
    def test_uses_custom_project_id(
        self,
        mock_monitor_cls: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Custom project_id is passed to create_error_task."""
        mock_monitor = MagicMock()
        mock_monitor.get_new_errors.return_value = [
            JournalError(
                unit="test.service",
                message="Error",
                priority=PRIORITY_ERR,
                timestamp=datetime.now(UTC),
                error_hash="hash1",
            ),
        ]
        mock_monitor_cls.return_value = mock_monitor
        mock_create.return_value = {"id": "task-123"}

        monitor_systemd_errors(project_id="my-project")

        mock_create.assert_called_once()
        call_args = mock_create.call_args[0]
        assert call_args[0] == "my-project"

    @patch("app.tasks.self_healing.SystemdMonitor")
    def test_handles_monitor_exception(
        self,
        mock_monitor_cls: MagicMock,
    ) -> None:
        """Monitor exceptions are handled gracefully."""
        mock_monitor = MagicMock()
        mock_monitor.get_new_errors.side_effect = Exception("Journal error")
        mock_monitor_cls.return_value = mock_monitor

        result = monitor_systemd_errors()

        assert result["errors"] == 1


class TestConstants:
    """Tests for task constants."""

    def test_max_tasks_per_run(self) -> None:
        """MAX_TASKS_PER_RUN is reasonable default."""
        assert MAX_TASKS_PER_RUN == 10
