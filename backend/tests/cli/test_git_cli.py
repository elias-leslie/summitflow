"""Test git CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cli.commands.git import _format_compact_repo, _get_repo_status, app
from cli.output_context import OutputContext

runner = CliRunner()


class TestGitStatus:
    """Tests for st git status command."""

    def test_status_help(self) -> None:
        """Verify help text displays."""
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0
        assert "Show git status for managed repositories" in result.stdout

    @patch("cli.commands.git._get_repo_status")
    @patch("cli.commands.git._get_managed_repos")
    def test_status_json_output(self, mock_managed: MagicMock, mock_status: MagicMock) -> None:
        """Test JSON output format for status."""
        mock_managed.return_value = [Path("/test/repo")]
        mock_status.return_value = {
            "path": "/test/repo",
            "name": "repo",
            "branch": "main",
            "uncommitted": 2,
            "ahead": 0,
            "behind": 0,
            "state": "dirty",
        }

        result = runner.invoke(app, ["status"], obj=OutputContext(compact=False))
        assert result.exit_code == 0
        assert "repositories" in result.stdout
        assert "total" in result.stdout

    @patch("cli.commands.git._get_repo_status")
    @patch("cli.commands.git._get_managed_repos")
    def test_status_toon_output(self, mock_managed: MagicMock, mock_status: MagicMock) -> None:
        """Test TOON format output for status."""
        mock_managed.return_value = [Path("/test/repo")]
        mock_status.return_value = {
            "path": "/test/repo",
            "name": "repo",
            "branch": "main",
            "uncommitted": 2,
            "ahead": 0,
            "behind": 0,
            "state": "dirty",
        }

        result = runner.invoke(app, ["status"], obj=OutputContext(compact=True))
        assert result.exit_code == 0
        assert "GIT[" in result.stdout


class TestGitSync:
    """Tests for st git sync command."""

    def test_sync_help(self) -> None:
        """Verify help text displays."""
        result = runner.invoke(app, ["sync", "--help"])
        assert result.exit_code == 0
        assert "Sync all managed repositories" in result.stdout

    @patch("cli.commands.git._get_repo_status")
    @patch("cli.commands.git._get_managed_repos")
    def test_sync_skips_dirty_repos(self, mock_managed: MagicMock, mock_status: MagicMock) -> None:
        """Test that sync skips repos with uncommitted changes."""
        mock_managed.return_value = [Path("/test/repo")]
        mock_status.return_value = {
            "path": "/test/repo",
            "name": "repo",
            "branch": "main",
            "uncommitted": 5,  # Has uncommitted changes
            "ahead": 0,
            "behind": 0,
            "state": "dirty",
        }

        result = runner.invoke(app, ["sync"], obj=OutputContext(compact=False))
        assert result.exit_code == 0
        assert "skipped" in result.stdout.lower() or "uncommitted" in result.stdout.lower()


class TestFinalizeTask:
    """Tests for st git finalize-task."""

    @patch("cli.commands.git.STClient")
    def test_finalize_task_calls_client(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.finalize_task_merge.return_value = {"status": "merged", "task_id": "task-1"}
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["finalize-task", "task-1"], obj=OutputContext(compact=False))

        assert result.exit_code == 0
        mock_client.finalize_task_merge.assert_called_once_with("task-1")
        assert '"status": "merged"' in result.stdout


class TestResolveConflict:
    """Tests for st git resolve-conflict."""

    @patch("cli.commands.git.STClient")
    def test_resolve_conflict_calls_client(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.resolve_task_conflict.return_value = {
            "status": "dispatched_for_conflict_resolution",
            "task_id": "task-1",
        }
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["resolve-conflict", "task-1"], obj=OutputContext(compact=False))

        assert result.exit_code == 0
        mock_client.resolve_task_conflict.assert_called_once_with("task-1")
        assert '"status": "dispatched_for_conflict_resolution"' in result.stdout


class TestSmartSync:
    """Tests for st git smart-sync."""

    @patch("cli.commands.git.STClient")
    def test_smart_sync_calls_client(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.smart_sync_project.return_value = {
            "status": "success",
            "project_id": "agent-hub",
        }
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["smart-sync", "agent-hub"], obj=OutputContext(compact=False))

        assert result.exit_code == 0
        mock_client.smart_sync_project.assert_called_once_with("agent-hub")
        assert '"status": "success"' in result.stdout


class TestFormatCompactRepo:
    """Tests for TOON format helper."""

    def test_format_clean_repo(self) -> None:
        """Test formatting a clean repository."""
        repo = {
            "name": "myrepo",
            "branch": "main",
            "state": "clean",
            "uncommitted": 0,
            "ahead": 0,
            "behind": 0,
        }
        result = _format_compact_repo(repo)
        assert "myrepo" in result
        assert "main" in result
        assert "clean" in result
        assert "uncommitted:0" in result

    def test_format_dirty_repo(self) -> None:
        """Test formatting a dirty repository."""
        repo = {
            "name": "dirtyrepo",
            "branch": "feature",
            "state": "dirty",
            "uncommitted": 5,
            "ahead": 2,
            "behind": 1,
        }
        result = _format_compact_repo(repo)
        assert "dirtyrepo" in result
        assert "dirty" in result
        assert "uncommitted:5" in result
        assert "ahead:2" in result
        assert "behind:1" in result


class TestGetRepoStatus:
    """Tests for repository status detection."""

    def test_nonexistent_repo_returns_none(self, tmp_path: Path) -> None:
        """Non-existent path returns None."""
        result = _get_repo_status(tmp_path / "nonexistent")
        assert result is None

    def test_non_git_dir_returns_none(self, tmp_path: Path) -> None:
        """Directory without .git returns None."""
        (tmp_path / "somedir").mkdir()
        result = _get_repo_status(tmp_path / "somedir")
        assert result is None
