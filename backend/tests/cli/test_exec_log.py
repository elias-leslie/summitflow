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
        mock.get_task_agent_sessions.return_value = {
            "task_id": "task-test123",
            "session_ids": ["sess-1"],
            "count": 1,
            "sessions": [
                {
                    "id": "sess-1",
                    "status": "active",
                    "effective_model": "claude-sonnet-4-6",
                    "live_activity": {
                        "health": "active",
                        "phase": "reading_file",
                        "summary": "Reading ActivityTimeline.tsx",
                    },
                }
            ],
        }
        mock.get_task_agent_events.return_value = {
            "task_id": "task-test123",
            "session_ids": ["sess-1"],
            "events": [
                {
                    "id": "evt-ah-1",
                    "session_id": "sess-1",
                    "turn": 1,
                    "sequence": 1,
                    "event_type": "assistant_message",
                    "content": "Planning the refactor",
                    "created_at": "2026-01-26T12:00:06-05:00",
                }
            ],
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
            assert "AH:agent:claude-sonnet-4-6:active/reading_file" in result.output
            assert "|AH|sess-1|[1.1] assistant_message" in result.output

    def test_exec_log_compact_includes_recent_agent_activity(self, mock_client: MagicMock) -> None:
        """Compact exec-log includes recent task-linked Agent Hub events."""
        with (
            patch("cli.commands.exec_monitor.STClient", return_value=mock_client),
            patch("cli.commands.exec_monitor.require_task_id", return_value="task-test123"),
        ):
            result = runner.invoke(app, ["exec-log", "task-test123"])

            assert result.exit_code == 0
            assert "|AH|sess-1|[1.1] assistant_message" in result.output
            assert "|AH|sess-1|  Planning the refactor" in result.output

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
            assert "Agent Sessions:" in result.output
            assert "Reading ActivityTimeline.tsx" in result.output
            assert "Recent Agent Activity:" in result.output
            assert "Subtasks:" in result.output
            assert "1.1:" in result.output
            assert "1.2:" in result.output

    def test_exec_log_hides_older_attempts_from_header_and_recent_activity(self, mock_client: MagicMock) -> None:
        """Retried tasks should default to the newest attempt cluster."""
        mock_client.get_events.return_value = {
            "events": [
                {
                    "id": "evt-task-old",
                    "timestamp": "2026-01-26T11:00:00+00:00",
                    "level": "info",
                    "message": "Old attempt started",
                    "source": "agent",
                    "visibility": "user",
                    "attributes": {},
                },
                {
                    "id": "evt-task-new",
                    "timestamp": "2026-01-26T12:01:00+00:00",
                    "level": "info",
                    "message": "Newest attempt started",
                    "source": "agent",
                    "visibility": "user",
                    "attributes": {},
                },
            ]
        }
        mock_client.get_task_agent_sessions.return_value = {
            "task_id": "task-test123",
            "session_ids": ["sess-old", "sess-new", "sess-feedback"],
            "count": 3,
            "sessions": [
                {
                    "id": "sess-old",
                    "status": "completed",
                    "agent_slug": "refactor",
                    "effective_model": "claude-sonnet-4-6",
                    "updated_at": "2026-01-26T11:00:00+00:00",
                    "live_activity": {
                        "health": "completed",
                        "phase": "completed",
                    },
                },
                {
                    "id": "sess-new",
                    "status": "completed",
                    "agent_slug": "refactor",
                    "effective_model": "claude-sonnet-4-6",
                    "updated_at": "2026-01-26T12:00:00+00:00",
                    "live_activity": {
                        "health": "completed",
                        "phase": "completed",
                    },
                },
                {
                    "id": "sess-feedback",
                    "status": "completed",
                    "agent_slug": "coder",
                    "effective_model": "codex/gpt-5.4",
                    "updated_at": "2026-01-26T12:03:00+00:00",
                    "live_activity": {
                        "health": "completed",
                        "phase": "completed",
                    },
                },
            ],
        }
        mock_client.get_task_agent_events.return_value = {
            "task_id": "task-test123",
            "session_ids": ["sess-old", "sess-new", "sess-feedback"],
            "events": [
                {
                    "id": "evt-old-1",
                    "session_id": "sess-old",
                    "turn": 1,
                    "sequence": 1,
                    "event_type": "assistant_message",
                    "content": "Old retry attempt",
                    "created_at": "2026-01-26T11:00:05+00:00",
                },
                {
                    "id": "evt-new-1",
                    "session_id": "sess-new",
                    "turn": 1,
                    "sequence": 1,
                    "event_type": "assistant_message",
                    "content": "Newest refactor attempt",
                    "created_at": "2026-01-26T12:00:05+00:00",
                },
                {
                    "id": "evt-feedback-1",
                    "session_id": "sess-feedback",
                    "turn": 1,
                    "sequence": 1,
                    "event_type": "assistant_message",
                    "content": "Feedback collection",
                    "created_at": "2026-01-26T12:03:05+00:00",
                },
            ],
        }

        with (
            patch("cli.commands.exec_monitor.STClient", return_value=mock_client),
            patch("cli.commands.exec_monitor.require_task_id", return_value="task-test123"),
        ):
            result = runner.invoke(app, ["exec-log", "task-test123"])

        assert result.exit_code == 0
        assert "AH:refactor:claude-sonnet-4-6:completed/completed,coder:gpt-5.4:completed/completed|hist=1" in result.output
        assert "sess-old" not in result.output
        assert "Old retry attempt" not in result.output
        assert "Old attempt started" not in result.output
        assert "Newest attempt started" in result.output
        assert "sess-new" in result.output
        assert "Feedback collection" in result.output

    def test_exec_log_json_output(self, mock_client: MagicMock) -> None:
        """Test exec-log --json outputs JSON lines."""
        with (
            patch("cli.commands.exec_monitor.STClient", return_value=mock_client),
            patch("cli.commands.exec_monitor.require_task_id", return_value="task-test123"),
        ):
            result = runner.invoke(app, ["exec-log", "task-test123", "--json"])

            assert result.exit_code == 0
            # JSON output should contain event data
            assert '"created_at"' in result.output
            assert '"event_type"' in result.output

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
            assert call_kwargs[1]["include_debug"] or call_kwargs[0][3] is True
