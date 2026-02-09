"""Integration tests for self-healing monitoring and task creation.

Tests the systemd journal monitor creating bug tasks from errors.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.services.self_healing.monitor import (
    PRIORITY_CRIT,
    PRIORITY_ERR,
    JournalError,
    create_error_task,
    process_journal_errors,
)


class TestSystemdMonitorIntegration:
    """Integration tests for SystemdMonitor task creation."""

    @pytest.fixture
    def mock_journal_error(self) -> JournalError:
        """Create a mock journal error."""
        return JournalError(
            unit="summitflow-backend.service",
            message="Database connection refused: Connection to PostgreSQL failed",
            priority=PRIORITY_ERR,
            timestamp=datetime(2026, 1, 18, 10, 30, 0),
            error_hash="abc123def456",
        )

    @patch("app.services.self_healing.monitor.create_task")
    @patch("app.services.self_healing.monitor.bug_task_exists_for_error")
    def test_create_error_task_creates_bug(
        self,
        mock_dedup: MagicMock,
        mock_create: MagicMock,
        mock_journal_error: JournalError,
    ) -> None:
        """create_error_task creates a bug task from journal error."""
        mock_dedup.return_value = False
        mock_create.return_value = {"id": "task-test123", "title": "Fix: Error"}

        result = create_error_task("summitflow", mock_journal_error)

        assert result is not None
        assert result["id"] == "task-test123"

        # Verify create_task was called with correct arguments
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["project_id"] == "summitflow"
        assert call_kwargs["task_type"] == "bug"
        assert call_kwargs["priority"] == 2
        assert call_kwargs["autonomous"] is True
        assert "Database connection refused" in call_kwargs["title"]

    @patch("app.services.self_healing.monitor.create_task")
    @patch("app.services.self_healing.monitor.bug_task_exists_for_error")
    def test_create_error_task_includes_full_context(
        self,
        mock_dedup: MagicMock,
        mock_create: MagicMock,
        mock_journal_error: JournalError,
    ) -> None:
        """Task description includes full error context."""
        mock_dedup.return_value = False
        mock_create.return_value = {"id": "task-test123"}

        create_error_task("summitflow", mock_journal_error)

        call_kwargs = mock_create.call_args[1]
        description = call_kwargs["description"]

        assert "summitflow-backend.service" in description
        assert "2026-01-18" in description
        assert "ERROR" in description
        assert "Database connection refused" in description
        assert "abc123def456" in description

    @patch("app.services.self_healing.monitor.create_task")
    @patch("app.services.self_healing.monitor.bug_task_exists_for_error")
    def test_create_error_task_skips_duplicate(
        self,
        mock_dedup: MagicMock,
        mock_create: MagicMock,
        mock_journal_error: JournalError,
    ) -> None:
        """Duplicate errors don't create new tasks."""
        mock_dedup.return_value = True  # Task already exists

        result = create_error_task("summitflow", mock_journal_error)

        assert result is None
        mock_create.assert_not_called()

    @patch("app.services.self_healing.monitor.create_task")
    @patch("app.services.self_healing.monitor.bug_task_exists_for_error")
    def test_create_error_task_skip_dedup_flag(
        self,
        mock_dedup: MagicMock,
        mock_create: MagicMock,
        mock_journal_error: JournalError,
    ) -> None:
        """skip_dedup flag bypasses deduplication check."""
        mock_dedup.return_value = True
        mock_create.return_value = {"id": "task-test123"}

        result = create_error_task("summitflow", mock_journal_error, skip_dedup=True)

        assert result is not None
        mock_dedup.assert_not_called()

    @patch("app.services.self_healing.monitor.create_task")
    @patch("app.services.self_healing.monitor.bug_task_exists_for_error")
    def test_create_error_task_truncates_long_message(
        self,
        mock_dedup: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Long error messages are truncated in title."""
        mock_dedup.return_value = False
        mock_create.return_value = {"id": "task-test123"}

        long_error = JournalError(
            unit="test.service",
            message="A" * 200,  # Very long message
            priority=PRIORITY_ERR,
            timestamp=datetime.now(UTC),
            error_hash="hash123",
        )

        create_error_task("summitflow", long_error)

        call_kwargs = mock_create.call_args[1]
        title = call_kwargs["title"]

        # Title should be truncated to ~80 chars + "Fix: " prefix
        assert len(title) < 100
        assert "..." in title

    @patch("app.services.self_healing.monitor.create_task")
    @patch("app.services.self_healing.monitor.bug_task_exists_for_error")
    def test_create_error_task_critical_priority(
        self,
        mock_dedup: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Critical errors include CRITICAL in description."""
        mock_dedup.return_value = False
        mock_create.return_value = {"id": "task-test123"}

        critical_error = JournalError(
            unit="test.service",
            message="Fatal error",
            priority=PRIORITY_CRIT,
            timestamp=datetime.now(UTC),
            error_hash="hash123",
        )

        create_error_task("summitflow", critical_error)

        call_kwargs = mock_create.call_args[1]
        description = call_kwargs["description"]

        assert "CRITICAL" in description


class TestProcessJournalErrors:
    """Tests for the main processing function."""

    @patch("app.services.self_healing.monitor.create_error_task")
    @patch("app.services.self_healing.monitor.SystemdMonitor")
    def test_process_creates_tasks_for_new_errors(
        self,
        mock_monitor_cls: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """process_journal_errors creates tasks for new errors."""
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

        results = process_journal_errors("summitflow")

        assert results["created"] == 2
        assert results["skipped"] == 0
        assert results["errors"] == 0
        assert mock_create.call_count == 2

    @patch("app.services.self_healing.monitor.create_error_task")
    @patch("app.services.self_healing.monitor.SystemdMonitor")
    def test_process_counts_skipped_duplicates(
        self,
        mock_monitor_cls: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Skipped duplicates are counted correctly."""
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
        mock_create.return_value = None  # Indicates duplicate

        results = process_journal_errors("summitflow")

        assert results["created"] == 0
        assert results["skipped"] == 1
        assert results["errors"] == 0

    @patch("app.services.self_healing.monitor.create_error_task")
    @patch("app.services.self_healing.monitor.SystemdMonitor")
    def test_process_counts_errors(
        self,
        mock_monitor_cls: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Task creation errors are counted correctly."""
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

        results = process_journal_errors("summitflow")

        assert results["created"] == 0
        assert results["skipped"] == 0
        assert results["errors"] == 1

    @patch("app.services.self_healing.monitor.create_error_task")
    def test_process_uses_provided_monitor(
        self,
        mock_create: MagicMock,
    ) -> None:
        """process_journal_errors uses provided monitor instance."""
        mock_monitor = MagicMock()
        mock_monitor.get_new_errors.return_value = []

        process_journal_errors("summitflow", monitor=mock_monitor)

        mock_monitor.get_new_errors.assert_called_once()

    @patch("app.services.self_healing.monitor.SystemdMonitor")
    def test_process_handles_empty_errors(
        self,
        mock_monitor_cls: MagicMock,
    ) -> None:
        """No errors results in zero counts."""
        mock_monitor = MagicMock()
        mock_monitor.get_new_errors.return_value = []
        mock_monitor_cls.return_value = mock_monitor

        results = process_journal_errors("summitflow")

        assert results["created"] == 0
        assert results["skipped"] == 0
        assert results["errors"] == 0

    @patch("app.services.self_healing.monitor.SystemdMonitor")
    def test_process_handles_monitor_exception(
        self,
        mock_monitor_cls: MagicMock,
    ) -> None:
        """Monitor exceptions are handled gracefully."""
        mock_monitor = MagicMock()
        mock_monitor.get_new_errors.side_effect = Exception("Journal error")
        mock_monitor_cls.return_value = mock_monitor

        results = process_journal_errors("summitflow")

        assert results["errors"] == 1


class TestOrchestrateTask:
    """Tests for the orchestrate_self_healing task."""

    @patch("app.tasks.self_healing.get_connection")
    def test_orchestrate_disabled_returns_early(
        self,
        mock_conn: MagicMock,
    ) -> None:
        """When disabled, task returns early without processing."""
        from app.tasks.self_healing import orchestrate_self_healing

        result = orchestrate_self_healing(enabled=False)

        assert result["enabled"] is False
        assert result["skipped"] is True
        mock_conn.assert_not_called()

    @patch("app.tasks.self_healing.get_connection")
    @patch("app.services.self_healing.orchestrator.SelfHealingOrchestrator")
    def test_orchestrate_no_errors_to_fix(
        self,
        mock_orch_cls: MagicMock,
        mock_conn: MagicMock,
    ) -> None:
        """When no errors, task returns without processing."""
        from app.tasks.self_healing import orchestrate_self_healing

        mock_orch = MagicMock()
        mock_orch.get_health_summary.return_value = {
            "should_run": False,
            "total_unfixed": 0,
            "projects_needing_fixes": 0,
        }
        mock_orch_cls.return_value = mock_orch

        result = orchestrate_self_healing()

        assert result["enabled"] is True
        assert result["projects_processed"] == 0
        assert "No unfixed errors" in result.get("message", "")
        mock_orch.poll_and_fix.assert_not_called()

    @patch("app.tasks.self_healing.get_connection")
    @patch("app.services.self_healing.orchestrator.SelfHealingOrchestrator")
    def test_orchestrate_processes_errors(
        self,
        mock_orch_cls: MagicMock,
        mock_conn: MagicMock,
    ) -> None:
        """Task processes errors when they exist."""
        from app.tasks.self_healing import orchestrate_self_healing

        mock_orch = MagicMock()
        mock_orch.get_health_summary.return_value = {
            "should_run": True,
            "total_unfixed": 5,
            "projects_needing_fixes": 1,
        }
        mock_orch.poll_and_fix.return_value = {
            "projects_processed": 1,
            "total_fixed": 3,
            "total_failed": 1,
            "total_escalated": 1,
            "by_check_type": {"ruff": {"fixed": 3, "failed": 1, "escalated": 1}},
            "by_project": {"summitflow": {"fixed": 3, "failed": 1, "escalated": 1}},
        }
        mock_orch_cls.return_value = mock_orch

        result = orchestrate_self_healing(max_errors=10)

        assert result["enabled"] is True
        assert result["projects_processed"] == 1
        assert result["total_fixed"] == 3
        assert result["total_failed"] == 1
        assert result["total_escalated"] == 1
        mock_orch.poll_and_fix.assert_called_once()
        mock_orch_cls.assert_called_once()

    @patch("app.tasks.self_healing.get_connection")
    @patch("app.services.self_healing.orchestrator.SelfHealingOrchestrator")
    def test_orchestrate_handles_exception(
        self,
        mock_orch_cls: MagicMock,
        mock_conn: MagicMock,
    ) -> None:
        """Exceptions are handled gracefully."""
        from app.tasks.self_healing import orchestrate_self_healing

        mock_orch = MagicMock()
        mock_orch.get_health_summary.side_effect = Exception("DB connection failed")
        mock_orch_cls.return_value = mock_orch

        result = orchestrate_self_healing()

        assert result["enabled"] is True
        assert "error" in result
        assert "DB connection failed" in result["error"]
        assert result["projects_processed"] == 0
