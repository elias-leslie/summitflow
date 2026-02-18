"""Tests for st exec-log CLI command.

Tests the exec-log command for viewing execution progress:
1. Command fetches execution logs
2. Filtering by task works
3. Output formatting correct (TOON and human-readable)
4. Error handling for invalid IDs
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from cli.commands.exec_monitor_formatters import subtask_summary as _subtask_summary

try:
    from cli.main import app
except ImportError as e:
    pytest.skip(f"Cannot import cli.main (missing dependency: {e})", allow_module_level=True)

runner = CliRunner()


class TestSubtaskSummary:
    """Tests for _subtask_summary helper function."""

    def test_empty_subtasks(self) -> None:
        """Empty subtasks list returns 0/0."""
        assert _subtask_summary([]) == "0/0"

    def test_all_passed(self) -> None:
        """All passed subtasks show X/X."""
        subtasks = [
            {"subtask_id": "1.1", "status": "passed"},
            {"subtask_id": "1.2", "status": "passed"},
        ]
        assert _subtask_summary(subtasks) == "2/2"

    def test_some_passed(self) -> None:
        """Some passed shows passed/total."""
        subtasks = [
            {"subtask_id": "1.1", "status": "passed"},
            {"subtask_id": "1.2", "status": "pending"},
            {"subtask_id": "1.3", "status": "pending"},
        ]
        assert _subtask_summary(subtasks) == "1/3"

    def test_failed_indicator(self) -> None:
        """Failed subtasks show (NF) indicator."""
        subtasks = [
            {"subtask_id": "1.1", "status": "passed"},
            {"subtask_id": "1.2", "status": "failed"},
        ]
        assert _subtask_summary(subtasks) == "1/2(1F)"

    def test_in_progress_indicator(self) -> None:
        """In-progress subtasks show (NW) indicator."""
        subtasks = [
            {"subtask_id": "1.1", "status": "passed"},
            {"subtask_id": "1.2", "status": "in_progress"},
            {"subtask_id": "1.3", "status": "in_progress"},
        ]
        assert _subtask_summary(subtasks) == "1/3(2W)"

    def test_failed_takes_precedence(self) -> None:
        """Failed indicator takes precedence over in_progress."""
        subtasks = [
            {"subtask_id": "1.1", "status": "passed"},
            {"subtask_id": "1.2", "status": "failed"},
            {"subtask_id": "1.3", "status": "in_progress"},
        ]
        assert _subtask_summary(subtasks) == "1/3(1F)"


class TestExecLogCommand:
    """Tests for exec-log CLI command."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create mock STClient for testing."""
        mock = MagicMock()
        mock.get_task.return_value = {
            "id": "task-test123",
            "project_id": "summitflow",
            "title": "Test Task for Execution Logging",
            "status": "running",
        }
        mock.get_subtasks.return_value = {
            "subtasks": [
                {"subtask_id": "1.1", "status": "passed", "description": "First subtask"},
                {"subtask_id": "1.2", "status": "in_progress", "description": "Second subtask"},
            ]
        }
        mock.get_events.return_value = {
            "events": [
                {
                    "id": "evt-1",
                    "timestamp": "2026-01-26T12:00:00-05:00",
                    "level": "info",
                    "message": "Task started",
                    "source": "agent",
                    "visibility": "user",
                    "attributes": {},
                },
                {
                    "id": "evt-2",
                    "timestamp": "2026-01-26T12:00:05-05:00",
                    "level": "info",
                    "message": "Tool call: bash",
                    "source": "agent",
                    "visibility": "user",
                    "attributes": {},
                },
            ]
        }
        return mock

    def test_exec_log_help(self) -> None:
        """Test exec-log --help shows correct info."""
        result = runner.invoke(app, ["exec-log", "--help"])
        assert result.exit_code == 0
        assert "View execution progress" in result.output
        assert "--follow" in result.output
        assert "--debug" in result.output
        assert "--json" in result.output

    def test_exec_log_compact_output(self, mock_client: MagicMock) -> None:
        """Test exec-log outputs TOON format."""
        with (
            patch("cli.commands.exec_monitor.STClient", return_value=mock_client),
            patch("cli.commands.exec_monitor.require_task_id", return_value="task-test123"),
        ):
            result = runner.invoke(app, ["exec-log", "task-test123"])

            assert result.exit_code == 0
            assert "EXEC:task-test123" in result.output
            assert "running" in result.output
            assert "1/2(1W)" in result.output  # subtask summary

    def test_exec_log_human_readable(self, mock_client: MagicMock) -> None:
        """Test exec-log human-readable format."""
        with (
            patch("cli.commands.exec_monitor.STClient", return_value=mock_client),
            patch("cli.commands.exec_monitor.require_task_id", return_value="task-test123"),
        ):
            result = runner.invoke(app, ["--no-compact", "exec-log", "task-test123"])

            assert result.exit_code == 0
            assert "Task: task-test123" in result.output
            assert "Status: running" in result.output
            assert "Subtasks:" in result.output
            assert "1.1:" in result.output
            assert "1.2:" in result.output

    def test_exec_log_json_output(self, mock_client: MagicMock) -> None:
        """Test exec-log --json outputs JSON lines."""
        with (
            patch("cli.commands.exec_monitor.STClient", return_value=mock_client),
            patch("cli.commands.exec_monitor.require_task_id", return_value="task-test123"),
        ):
            result = runner.invoke(app, ["exec-log", "task-test123", "--json"])

            assert result.exit_code == 0
            # JSON output should contain event data
            assert '"timestamp"' in result.output
            assert '"message"' in result.output

    def test_exec_log_invalid_task_id(self) -> None:
        """Test exec-log with invalid task ID shows error."""
        from cli.client import APIError

        mock = MagicMock()
        mock.get_task.side_effect = APIError(404, "Task not found")

        with (
            patch("cli.commands.exec_monitor.STClient", return_value=mock),
            patch("cli.commands.exec_monitor.require_task_id", return_value="task-invalid"),
        ):
            result = runner.invoke(app, ["exec-log", "task-invalid"])

            # handle_api_error calls typer.Exit(1)
            assert result.exit_code == 1
            assert "404" in result.output or "not found" in result.output.lower()

    def test_exec_log_limit_option(self, mock_client: MagicMock) -> None:
        """Test exec-log respects --limit option."""
        with (
            patch("cli.commands.exec_monitor.STClient", return_value=mock_client),
            patch("cli.commands.exec_monitor.require_task_id", return_value="task-test123"),
        ):
            result = runner.invoke(app, ["exec-log", "task-test123", "-n", "10"])

            assert result.exit_code == 0
            mock_client.get_events.assert_called_once()
            call_kwargs = mock_client.get_events.call_args
            assert call_kwargs[1]["limit"] == 10 or call_kwargs[0][2] == 10

    def test_exec_log_debug_option(self, mock_client: MagicMock) -> None:
        """Test exec-log --debug includes debug events."""
        with (
            patch("cli.commands.exec_monitor.STClient", return_value=mock_client),
            patch("cli.commands.exec_monitor.require_task_id", return_value="task-test123"),
        ):
            result = runner.invoke(app, ["exec-log", "task-test123", "--debug"])

            assert result.exit_code == 0
            mock_client.get_events.assert_called_once()
            call_kwargs = mock_client.get_events.call_args
            assert call_kwargs[1]["include_debug"] is True or call_kwargs[0][3] is True


class TestExecMonitorAlias:
    """Test that exec-monitor alias works."""

    def test_exec_monitor_alias_exists(self) -> None:
        """Test exec-monitor command exists as alias."""
        result = runner.invoke(app, ["exec-monitor", "--help"])
        assert result.exit_code == 0
        assert "View execution progress" in result.output

    def test_exec_monitor_same_as_exec_log(self) -> None:
        """Test exec-monitor produces same output as exec-log."""
        mock = MagicMock()
        mock.get_task.return_value = {
            "id": "task-alias-test",
            "project_id": "summitflow",
            "title": "Alias Test",
            "status": "pending",
        }
        mock.get_subtasks.return_value = {"subtasks": []}
        mock.get_events.return_value = {"events": []}

        with (
            patch("cli.commands.exec_monitor.STClient", return_value=mock),
            patch("cli.commands.exec_monitor.require_task_id", return_value="task-alias-test"),
        ):
            log_result = runner.invoke(app, ["exec-log", "task-alias-test"])
            monitor_result = runner.invoke(app, ["exec-monitor", "task-alias-test"])

            assert log_result.output == monitor_result.output
