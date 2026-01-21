"""Tests for st work context management."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from cli.commands.tasks import app as tasks_app
from cli.context import (
    clear_active_task_id,
    get_active_context,
    get_active_task_id,
    require_task_id,
    set_active_task_id,
)


@pytest.fixture
def temp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override home directory for testing."""
    monkeypatch.setenv("HOME", str(tmp_path))
    # Also mock _get_git_root to return None (no local context)
    monkeypatch.setattr("cli.context._get_git_root", lambda: None)
    return tmp_path


@pytest.fixture
def temp_git_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override git root directory for testing (project-local context)."""
    monkeypatch.setattr("cli.context._get_git_root", lambda: tmp_path)
    return tmp_path


class TestContextModule:
    """Tests for cli/context.py functions."""

    def test_set_and_get_global_context(self, temp_home: Path) -> None:
        """Test setting and getting context in global location."""
        # Set context
        path = set_active_task_id("task-abc123", project_id="proj-1")

        assert path == temp_home / ".summitflow" / "context.json"
        assert path.exists()

        # Read back
        task_id = get_active_task_id()
        assert task_id == "task-abc123"

        # Full context
        ctx = get_active_context()
        assert ctx is not None
        assert ctx.task_id == "task-abc123"
        assert ctx.project_id == "proj-1"
        assert ctx.set_at  # Should have timestamp

    def test_set_context_in_git_repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test context is stored locally when in a git repo."""
        home_dir = tmp_path / "home"
        git_root = tmp_path / "project"
        home_dir.mkdir()
        git_root.mkdir()

        monkeypatch.setenv("HOME", str(home_dir))
        monkeypatch.setattr("cli.context._get_git_root", lambda: git_root)

        path = set_active_task_id("task-local")

        # Should be in git root, not home
        assert path == git_root / ".summitflow" / "context.json"
        assert path.exists()

        # Global file should not exist
        global_path = home_dir / ".summitflow" / "context.json"
        assert not global_path.exists()

    def test_get_context_priority_env_first(
        self, temp_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Environment variable takes priority over file."""
        # Set file context
        set_active_task_id("task-from-file")

        # Set env variable
        monkeypatch.setenv("ST_CURRENT_TASK_ID", "task-from-env")

        task_id = get_active_task_id()
        assert task_id == "task-from-env"

    def test_get_context_priority_local_over_global(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Local context takes priority over global."""
        home_dir = tmp_path / "home"
        git_root = tmp_path / "project"
        home_dir.mkdir()
        git_root.mkdir()

        monkeypatch.setenv("HOME", str(home_dir))

        # Write global context
        global_dir = home_dir / ".summitflow"
        global_dir.mkdir(parents=True)
        (global_dir / "context.json").write_text(
            json.dumps({"task_id": "task-global", "set_at": ""})
        )

        # Write local context
        local_dir = git_root / ".summitflow"
        local_dir.mkdir(parents=True)
        (local_dir / "context.json").write_text(json.dumps({"task_id": "task-local", "set_at": ""}))

        # Mock git root to point to project
        monkeypatch.setattr("cli.context._get_git_root", lambda: git_root)

        task_id = get_active_task_id()
        assert task_id == "task-local"

    def test_clear_context(self, temp_home: Path) -> None:
        """Test clearing context."""
        # Set then clear
        set_active_task_id("task-to-clear")
        assert get_active_task_id() == "task-to-clear"

        cleared = clear_active_task_id()
        assert cleared is True
        assert get_active_task_id() is None

    def test_clear_when_no_context(self, temp_home: Path) -> None:
        """Clear returns False when no context exists."""
        cleared = clear_active_task_id()
        assert cleared is False

    def test_get_context_returns_none_when_empty(self, temp_home: Path) -> None:
        """get_active_task_id returns None when no context set."""
        result = get_active_task_id()
        assert result is None

    def test_invalid_json_gracefully_ignored(self, temp_home: Path) -> None:
        """Malformed context files are gracefully ignored."""
        context_dir = temp_home / ".summitflow"
        context_dir.mkdir(parents=True)
        (context_dir / "context.json").write_text("not valid json{")

        result = get_active_task_id()
        assert result is None


class TestRequireTaskId:
    """Tests for require_task_id helper."""

    def test_explicit_task_id_returned(self, temp_home: Path) -> None:
        """Explicit argument is returned as-is."""
        result = require_task_id("explicit-task")
        assert result == "explicit-task"

    def test_fallback_to_context(self, temp_home: Path) -> None:
        """Falls back to active context when no explicit ID."""
        set_active_task_id("context-task")
        result = require_task_id(None)
        assert result == "context-task"

    def test_error_when_no_context(self, temp_home: Path) -> None:
        """Raises typer.Exit when no explicit ID and no context."""
        from click.exceptions import Exit

        with pytest.raises(Exit):
            require_task_id(None)


class TestWorkCommand:
    """Tests for st work command."""

    runner = CliRunner()

    def test_work_show_no_context(self, temp_home: Path) -> None:
        """st work --show when no context set."""
        with patch("cli.context._get_git_root", return_value=None):
            result = self.runner.invoke(tasks_app, ["work", "--show"])
        assert result.exit_code == 0
        assert "No active context" in result.stdout

    def test_work_show_with_context(self, temp_home: Path) -> None:
        """st work --show when context is set."""
        with patch("cli.context._get_git_root", return_value=None):
            set_active_task_id("task-xyz")
            result = self.runner.invoke(tasks_app, ["work", "--show"])
        assert result.exit_code == 0
        assert "ACTIVE:task-xyz" in result.stdout

    def test_work_done_clears_context(self, temp_home: Path) -> None:
        """st work --done clears active context."""
        with patch("cli.context._get_git_root", return_value=None):
            set_active_task_id("task-to-clear")
            result = self.runner.invoke(tasks_app, ["work", "--done"])
        assert result.exit_code == 0
        assert "CLEARED" in result.stdout

        with patch("cli.context._get_git_root", return_value=None):
            assert get_active_task_id() is None

    @patch("cli.commands.tasks.STClient")
    def test_work_set_validates_task(self, mock_client_cls: MagicMock, temp_home: Path) -> None:
        """st work <task-id> validates task exists."""
        mock_client = MagicMock()
        mock_client.get_task.return_value = {
            "id": "task-valid",
            "title": "Test Task",
            "status": "pending",
            "project_id": "proj-1",
        }
        mock_client_cls.return_value = mock_client

        with patch("cli.context._get_git_root", return_value=None):
            result = self.runner.invoke(tasks_app, ["work", "task-valid"])

        assert result.exit_code == 0
        assert "ACTIVE:task-valid" in result.stdout
        assert "Test Task" in result.stdout
        mock_client.get_task.assert_called_once_with("task-valid")

    @patch("cli.commands.tasks.STClient")
    def test_work_set_error_on_invalid_task(
        self, mock_client_cls: MagicMock, temp_home: Path
    ) -> None:
        """st work <task-id> errors when task doesn't exist."""
        from cli.client import APIError

        mock_client = MagicMock()
        mock_client.get_task.side_effect = APIError(404, "Task not found")
        mock_client_cls.return_value = mock_client

        with patch("cli.context._get_git_root", return_value=None):
            result = self.runner.invoke(tasks_app, ["work", "task-invalid"])

        assert result.exit_code == 1


class TestCloseWithContext:
    """Tests for st close using active context."""

    runner = CliRunner()

    @patch("cli.commands.tasks.STClient")
    def test_close_uses_context_when_no_id(
        self, mock_client_cls: MagicMock, temp_home: Path
    ) -> None:
        """st close without task_id uses active context."""
        mock_client = MagicMock()
        mock_client.get_task.return_value = {
            "id": "task-context",
            "status": "running",
            "qa_status": "passed",
        }
        mock_client.close_task.return_value = {
            "id": "task-context",
            "status": "completed",
        }
        mock_client_cls.return_value = mock_client

        with patch("cli.context._get_git_root", return_value=None):
            set_active_task_id("task-context")
            self.runner.invoke(tasks_app, ["close"])

        # Should have called close_task with the context task_id
        mock_client.close_task.assert_called_once_with("task-context", reason=None)

    def test_close_errors_when_no_context(self, temp_home: Path) -> None:
        """st close without task_id errors when no context set."""
        with patch("cli.context._get_git_root", return_value=None):
            result = self.runner.invoke(tasks_app, ["close"], catch_exceptions=False)

        assert result.exit_code == 1
        # Error output goes to stderr which is captured in result.output
        assert "No task specified" in result.output or "st work" in result.output
