"""Tests for st cleanup path safeguards."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from app.services.destructive_path_guard import GuardConflict, GuardDecision
from cli.commands.cleanup import app
from cli.commands.cleanup_paths import _get_project_root

runner = CliRunner()


class TestCleanupPath:
    """Tests for safe repo-local cleanup."""

    def test_get_project_root_prefers_current_git_worktree_over_configured_project_root(self) -> None:
        """Worktree-local cleanup should resolve against the active git root first."""
        lane_root = Path("/srv/workspaces/lanes/summitflow/task-fd552cef")
        project_root = Path("/srv/workspaces/projects/summitflow")

        with (
            patch("cli.commands.cleanup_paths.get_repo_root", return_value=lane_root),
            patch(
                "cli.commands.cleanup_paths.get_config_optional",
                return_value=SimpleNamespace(project_root=str(project_root)),
            ),
        ):
            resolved = _get_project_root()

        assert resolved == lane_root

    def test_cleanup_path_dry_run_reports_repo_relative_target(self, tmp_path: Path) -> None:
        """Dry-run should report the target without deleting it."""
        repo_root = tmp_path / "repo"
        target = repo_root / "legacy" / "dead.txt"
        target.parent.mkdir(parents=True)
        target.write_text("old\n", encoding="utf-8")

        with patch("cli.commands.cleanup_paths._get_project_root", return_value=repo_root):
            result = runner.invoke(app, ["path", str(target), "--dry-run"])

        assert result.exit_code == 0
        assert '"path": "legacy/dead.txt"' in result.output
        assert target.exists()

    def test_cleanup_path_requires_recursive_for_directories(self, tmp_path: Path) -> None:
        """Directory deletion must require --recursive."""
        repo_root = tmp_path / "repo"
        target = repo_root / "legacy"
        target.mkdir(parents=True)

        with patch("cli.commands.cleanup_paths._get_project_root", return_value=repo_root):
            result = runner.invoke(app, ["path", str(target)])

        assert result.exit_code == 1
        assert "Directory cleanup requires --recursive" in result.output
        assert target.exists()

    def test_cleanup_path_blocks_protected_directories(self, tmp_path: Path) -> None:
        """Protected directories should never be deletable."""
        repo_root = tmp_path / "repo"
        target = repo_root / ".git"
        target.mkdir(parents=True)

        with patch("cli.commands.cleanup_paths._get_project_root", return_value=repo_root):
            result = runner.invoke(app, ["path", str(target), "--recursive"])

        assert result.exit_code == 1
        assert "Refusing to cleanup protected path" in result.output
        assert target.exists()

    def test_cleanup_path_deletes_directory_with_recursive(self, tmp_path: Path) -> None:
        """Recursive cleanup should remove repo-local directories."""
        repo_root = tmp_path / "repo"
        target = repo_root / "legacy"
        nested = target / "dead.txt"
        nested.parent.mkdir(parents=True)
        nested.write_text("old\n", encoding="utf-8")

        with patch("cli.commands.cleanup_paths._get_project_root", return_value=repo_root):
            result = runner.invoke(app, ["path", str(target), "--recursive"])

        assert result.exit_code == 0
        assert '"deleted": true' in result.output
        assert not target.exists()

    def test_cleanup_path_blocks_foreign_live_owner(self, tmp_path: Path) -> None:
        """Cleanup should refuse destructive deletes in another live session's checkout."""
        repo_root = tmp_path / "repo"
        target = repo_root / "docs" / "plans" / "vantage-rollout-plan.md"
        target.parent.mkdir(parents=True)
        target.write_text("plan\n", encoding="utf-8")

        blocked = GuardDecision(
            blocked=True,
            project_id="summitflow",
            repo_root=str(repo_root),
            current_session_id="sess-self",
            destructive_paths=("docs/plans/vantage-rollout-plan.md",),
            conflicts=(
                GuardConflict(
                    session_id="sess-foreign",
                    task_id=None,
                    branch="main",
                    worktree_path=str(repo_root),
                    reason="unknown_scope",
                    paths=("docs/plans/vantage-rollout-plan.md",),
                ),
            ),
        )

        with (
            patch("cli.commands.cleanup_paths._get_project_root", return_value=repo_root),
            patch("cli.commands.cleanup_paths.check_destructive_paths", return_value=blocked),
        ):
            result = runner.invoke(app, ["path", str(target)])

        assert result.exit_code == 1
        assert "Refusing destructive path action" in result.output
        assert target.exists()
