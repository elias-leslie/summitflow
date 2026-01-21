"""Tests for browser error monitoring.

ac-005: Browser console errors from explorer scan create bug tasks automatically
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.self_healing.browser_monitor import (
    BrowserError,
    BrowserErrorMonitor,
    compute_console_error_hash,
    create_browser_error_task,
    process_browser_errors,
)


class TestComputeConsoleErrorHash:
    """Tests for console error hash computation."""

    def test_hash_is_stable(self) -> None:
        """Same input produces same hash."""
        hash1 = compute_console_error_hash("/tasks", "TypeError: undefined")
        hash2 = compute_console_error_hash("/tasks", "TypeError: undefined")
        assert hash1 == hash2

    def test_different_errors_different_hashes(self) -> None:
        """Different errors produce different hashes."""
        hash1 = compute_console_error_hash("/tasks", "Error A")
        hash2 = compute_console_error_hash("/tasks", "Error B")
        assert hash1 != hash2

    def test_different_pages_different_hashes(self) -> None:
        """Different pages produce different hashes."""
        hash1 = compute_console_error_hash("/tasks", "Error")
        hash2 = compute_console_error_hash("/projects", "Error")
        assert hash1 != hash2

    def test_hash_length(self) -> None:
        """Hash is 16 characters."""
        hash_val = compute_console_error_hash("/page", "error")
        assert len(hash_val) == 16

    def test_case_normalization(self) -> None:
        """Error message is normalized (lowercase)."""
        hash1 = compute_console_error_hash("/page", "TypeError: UNDEFINED")
        hash2 = compute_console_error_hash("/page", "typeerror: undefined")
        assert hash1 == hash2

    def test_long_message_truncation(self) -> None:
        """Long error messages are truncated for stable hashing."""
        base_error = "Error: " + "x" * 300
        hash1 = compute_console_error_hash("/page", base_error)
        hash2 = compute_console_error_hash("/page", base_error[:200])
        # Should match due to truncation at 200 chars
        assert hash1 == hash2


class TestBrowserErrorMonitor:
    """Tests for BrowserErrorMonitor class."""

    @patch("app.services.self_healing.browser_monitor.get_entries_with_console_errors")
    def test_detect_errors_returns_browser_errors(self, mock_get_entries: MagicMock) -> None:
        """detect_errors returns BrowserError objects."""
        mock_get_entries.return_value = [
            {
                "id": 1,
                "path": "/tasks",
                "metadata": {
                    "console_error_count": 2,
                    "console_errors": ["TypeError: foo", "ReferenceError: bar"],
                },
                "last_scanned_at": "2026-01-21T10:00:00Z",
            }
        ]

        monitor = BrowserErrorMonitor("summitflow")
        errors = monitor.detect_errors()

        assert len(errors) == 2
        assert all(isinstance(e, BrowserError) for e in errors)
        assert errors[0].page_path == "/tasks"
        assert errors[0].error_message == "TypeError: foo"

    @patch("app.services.self_healing.browser_monitor.get_entries_with_console_errors")
    def test_get_new_errors_filters_seen(self, mock_get_entries: MagicMock) -> None:
        """get_new_errors filters out previously seen errors."""
        mock_get_entries.return_value = [
            {
                "id": 1,
                "path": "/tasks",
                "metadata": {
                    "console_error_count": 1,
                    "console_errors": ["TypeError: foo"],
                },
                "last_scanned_at": "2026-01-21T10:00:00Z",
            }
        ]

        monitor = BrowserErrorMonitor("summitflow")

        # First call returns the error
        new_errors1 = monitor.get_new_errors()
        assert len(new_errors1) == 1

        # Second call returns empty (already seen)
        new_errors2 = monitor.get_new_errors()
        assert len(new_errors2) == 0

    @patch("app.services.self_healing.browser_monitor.get_entries_with_console_errors")
    def test_mark_seen_prevents_duplicate_detection(self, mock_get_entries: MagicMock) -> None:
        """mark_seen prevents error from being returned."""
        mock_get_entries.return_value = [
            {
                "id": 1,
                "path": "/tasks",
                "metadata": {
                    "console_error_count": 1,
                    "console_errors": ["TypeError: foo"],
                },
                "last_scanned_at": "2026-01-21T10:00:00Z",
            }
        ]

        monitor = BrowserErrorMonitor("summitflow")

        # Pre-mark the hash
        error_hash = compute_console_error_hash("/tasks", "TypeError: foo")
        monitor.mark_seen(error_hash)

        # Should return empty since hash is marked seen
        new_errors = monitor.get_new_errors()
        assert len(new_errors) == 0


class TestCreateBrowserErrorTask:
    """Tests for create_browser_error_task function."""

    @patch("app.services.self_healing.browser_monitor.create_task")
    @patch("app.services.self_healing.browser_monitor.bug_task_exists_for_error")
    def test_creates_bug_task(
        self, mock_dedup: MagicMock, mock_create: MagicMock
    ) -> None:
        """Creates bug task from browser error."""
        mock_dedup.return_value = False
        mock_create.return_value = {"id": "task-browser123"}

        error = BrowserError(
            page_path="/tasks",
            page_id=1,
            error_message="TypeError: Cannot read property 'foo' of undefined",
            error_count=3,
            detected_at="2026-01-21T10:00:00Z",
            error_hash="abc123def456",
        )

        result = create_browser_error_task("summitflow", error)

        assert result == {"id": "task-browser123"}
        mock_create.assert_called_once()

        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["project_id"] == "summitflow"
        assert call_kwargs["task_type"] == "bug"
        assert call_kwargs["priority"] == 2
        assert call_kwargs["autonomous"] is True
        assert "Fix console error" in call_kwargs["title"]
        assert "TypeError" in call_kwargs["title"]

    @patch("app.services.self_healing.browser_monitor.create_task")
    @patch("app.services.self_healing.browser_monitor.bug_task_exists_for_error")
    def test_skips_duplicate(self, mock_dedup: MagicMock, mock_create: MagicMock) -> None:
        """Skips creating task if duplicate exists."""
        mock_dedup.return_value = True

        error = BrowserError(
            page_path="/tasks",
            page_id=1,
            error_message="Error",
            error_count=1,
            detected_at="2026-01-21T10:00:00Z",
            error_hash="abc123",
        )

        result = create_browser_error_task("summitflow", error)

        assert result is None
        mock_create.assert_not_called()

    @patch("app.services.self_healing.browser_monitor.create_task")
    @patch("app.services.self_healing.browser_monitor.bug_task_exists_for_error")
    def test_skip_dedup_bypasses_check(
        self, mock_dedup: MagicMock, mock_create: MagicMock
    ) -> None:
        """skip_dedup=True bypasses duplicate check."""
        mock_create.return_value = {"id": "task-123"}

        error = BrowserError(
            page_path="/tasks",
            page_id=1,
            error_message="Error",
            error_count=1,
            detected_at="2026-01-21T10:00:00Z",
            error_hash="abc123",
        )

        result = create_browser_error_task("summitflow", error, skip_dedup=True)

        assert result is not None
        mock_dedup.assert_not_called()

    @patch("app.services.self_healing.browser_monitor.create_task")
    @patch("app.services.self_healing.browser_monitor.bug_task_exists_for_error")
    def test_includes_context_in_description(
        self, mock_dedup: MagicMock, mock_create: MagicMock
    ) -> None:
        """Task description includes error context."""
        mock_dedup.return_value = False
        mock_create.return_value = {"id": "task-123"}

        error = BrowserError(
            page_path="/tasks/123",
            page_id=42,
            error_message="TypeError: foo is not a function",
            error_count=5,
            detected_at="2026-01-21T10:00:00Z",
            error_hash="abc123def456",
        )

        create_browser_error_task("summitflow", error)

        call_kwargs = mock_create.call_args[1]
        description = call_kwargs["description"]

        assert "/tasks/123" in description
        assert "TypeError: foo is not a function" in description
        assert "5 total errors" in description
        assert "2026-01-21" in description


class TestProcessBrowserErrors:
    """Tests for process_browser_errors function."""

    @patch("app.services.self_healing.browser_monitor.create_browser_error_task")
    @patch("app.services.self_healing.browser_monitor.BrowserErrorMonitor")
    def test_processes_all_errors(
        self, mock_monitor_cls: MagicMock, mock_create: MagicMock
    ) -> None:
        """Processes all new errors from monitor."""
        mock_monitor = MagicMock()
        mock_monitor.get_new_errors.return_value = [
            BrowserError("/a", 1, "Err A", 1, "", "hash1"),
            BrowserError("/b", 2, "Err B", 1, "", "hash2"),
        ]
        mock_monitor_cls.return_value = mock_monitor
        mock_create.side_effect = [{"id": "t1"}, {"id": "t2"}]

        results = process_browser_errors("summitflow")

        assert results["created"] == 2
        assert results["skipped"] == 0
        assert results["errors"] == 0

    @patch("app.services.self_healing.browser_monitor.create_browser_error_task")
    @patch("app.services.self_healing.browser_monitor.BrowserErrorMonitor")
    def test_counts_skipped_duplicates(
        self, mock_monitor_cls: MagicMock, mock_create: MagicMock
    ) -> None:
        """Counts skipped duplicates correctly."""
        mock_monitor = MagicMock()
        mock_monitor.get_new_errors.return_value = [
            BrowserError("/a", 1, "Err", 1, "", "hash1"),
        ]
        mock_monitor_cls.return_value = mock_monitor
        mock_create.return_value = None  # Duplicate skipped

        results = process_browser_errors("summitflow")

        assert results["created"] == 0
        assert results["skipped"] == 1
        assert results["errors"] == 0

    @patch("app.services.self_healing.browser_monitor.create_browser_error_task")
    @patch("app.services.self_healing.browser_monitor.BrowserErrorMonitor")
    def test_handles_creation_error(
        self, mock_monitor_cls: MagicMock, mock_create: MagicMock
    ) -> None:
        """Handles task creation errors gracefully."""
        mock_monitor = MagicMock()
        mock_monitor.get_new_errors.return_value = [
            BrowserError("/a", 1, "Err", 1, "", "hash1"),
        ]
        mock_monitor_cls.return_value = mock_monitor
        mock_create.side_effect = Exception("DB error")

        results = process_browser_errors("summitflow")

        assert results["created"] == 0
        assert results["errors"] == 1

    @patch("app.services.self_healing.browser_monitor.BrowserErrorMonitor")
    def test_accepts_custom_monitor(self, mock_monitor_cls: MagicMock) -> None:
        """Uses provided monitor instead of creating new one."""
        custom_monitor = MagicMock()
        custom_monitor.get_new_errors.return_value = []

        process_browser_errors("summitflow", monitor=custom_monitor)

        mock_monitor_cls.assert_not_called()
        custom_monitor.get_new_errors.assert_called_once()
