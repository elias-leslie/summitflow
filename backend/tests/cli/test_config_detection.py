"""Tests for CLI project detection across worktrees and detached checkouts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from cli import config as config_mod


class TestProjectDetection:
    def test_detect_project_from_cwd_detached_worktree_returns_canonical_root(self) -> None:
        """Detached helper worktrees should resolve to the canonical project root."""
        projects = [
            {
                "id": "summitflow",
                "root_path": "/home/kasadis/summitflow",
            }
        ]
        cwd = Path("/tmp/summitflow-merge-main").resolve()

        with (
            patch.object(config_mod, "_fetch_projects_with_retry", return_value=projects),
            patch.object(
                config_mod,
                "canonical_repo_root",
                return_value=Path("/home/kasadis/summitflow"),
            ),
            patch("cli.config.Path.cwd", return_value=cwd),
        ):
            project_id, root_path = config_mod._detect_project_from_cwd("http://localhost:8001/api")

        assert project_id == "summitflow"
        assert root_path == "/home/kasadis/summitflow"

    def test_detect_project_from_cwd_direct_match_returns_checkout_path(self) -> None:
        """Normal repo-root detection should keep using the current checkout path."""
        projects = [
            {
                "id": "summitflow",
                "root_path": "/home/kasadis/summitflow",
            }
        ]
        cwd = Path("/home/kasadis/summitflow/backend").resolve()

        with (
            patch.object(config_mod, "_fetch_projects_with_retry", return_value=projects),
            patch.object(config_mod, "canonical_repo_root", return_value=None),
            patch("cli.config.Path.cwd", return_value=cwd),
        ):
            project_id, root_path = config_mod._detect_project_from_cwd("http://localhost:8001/api")

        assert project_id == "summitflow"
        assert root_path == "/home/kasadis/summitflow"
