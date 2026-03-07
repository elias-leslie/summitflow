"""Tests for st cleanup path safeguards."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands.cleanup import app

runner = CliRunner()


class TestCleanupPath:
    """Tests for safe repo-local cleanup."""

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
