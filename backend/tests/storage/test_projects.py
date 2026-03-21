"""Unit tests for projects storage layer.

Focuses on build_project_env() behavior, especially PYTHONPATH injection
when a working_dir is provided.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_venv(base_path: os.PathLike[str]) -> None:
    """Create a minimal .venv/bin/python structure under base_path."""
    from pathlib import Path

    venv_bin = Path(base_path) / ".venv" / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    python = venv_bin / "python"
    python.touch()


def _mock_get_root_path(root_path: str) -> MagicMock:
    """Return a mock for get_project_root_path that yields root_path."""
    mock = MagicMock(return_value=root_path)
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBuildProjectEnv:
    """Tests for build_project_env() in app.storage.projects."""

    @patch("app.storage.projects.get_project_root_path")
    def test_build_project_env_with_working_dir_sets_pythonpath(
        self,
        mock_get_root: MagicMock,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        """When working_dir has a backend/ subdirectory, PYTHONPATH includes it.

        Arrange: a main repo with a .venv and a worktree dir with a backend/
        subdirectory.
        Act: call build_project_env() with the worktree as working_dir.
        Assert: PYTHONPATH is set to <working_dir>/backend.
        """
        from app.storage.projects import build_project_env

        # Arrange
        main_repo = tmp_path / "main-repo"
        _make_venv(main_repo)

        worktree = tmp_path / "worktrees" / "feature-branch"
        backend_dir = worktree / "backend"
        backend_dir.mkdir(parents=True)

        mock_get_root.return_value = str(main_repo)

        env_before = os.environ.copy()
        env_before.pop("PYTHONPATH", None)

        with patch.dict(os.environ, env_before, clear=True):
            # Act
            result = build_project_env(
                project_id="proj-abc123",
                working_dir=str(worktree),
            )

        # Assert
        assert "PYTHONPATH" in result
        assert str(backend_dir) in result["PYTHONPATH"]

    @patch("app.storage.projects.get_project_root_path")
    def test_build_project_env_no_backend_dir_omits_pythonpath(
        self,
        mock_get_root: MagicMock,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        """When working_dir has no backend/ subdirectory, PYTHONPATH is not set.

        Arrange: a main repo with a .venv and a worktree dir without backend/.
        Act: call build_project_env() with the bare worktree as working_dir.
        Assert: PYTHONPATH is absent from the returned env dict.
        """
        from app.storage.projects import build_project_env

        # Arrange
        main_repo = tmp_path / "main-repo"
        _make_venv(main_repo)

        worktree = tmp_path / "worktrees" / "no-backend-branch"
        worktree.mkdir(parents=True)
        # Intentionally do NOT create worktree/backend/

        mock_get_root.return_value = str(main_repo)

        env_before = os.environ.copy()
        env_before.pop("PYTHONPATH", None)

        with patch.dict(os.environ, env_before, clear=True):
            # Act
            result = build_project_env(
                project_id="proj-abc123",
                working_dir=str(worktree),
            )

        # Assert
        assert "PYTHONPATH" not in result


class TestFindProjectByCwd:
    """Tests for path-aware project detection."""

    @patch("app.storage.projects.list_projects")
    def test_returns_longest_matching_root_for_nested_paths(
        self,
        mock_list_projects: MagicMock,
        tmp_path: Path,
    ) -> None:
        from app.storage.projects import find_project_by_cwd

        workspace = tmp_path / "workspace"
        repo_root = workspace / "summitflow"
        nested_root = repo_root / "tools"
        cwd = nested_root / "scripts"
        cwd.mkdir(parents=True)

        mock_list_projects.return_value = [
            {"id": "summitflow", "name": "SummitFlow", "root_path": str(repo_root)},
            {"id": "tools", "name": "Tools", "root_path": str(nested_root)},
        ]

        result = find_project_by_cwd(str(cwd))

        assert result == {"id": "tools", "name": "Tools", "root_path": str(nested_root)}

    @patch("app.storage.projects.list_projects")
    def test_resolves_relative_cwd_before_matching(
        self,
        mock_list_projects: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.storage.projects import find_project_by_cwd

        repo_root = tmp_path / "summitflow"
        child_dir = repo_root / "backend" / "app"
        child_dir.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)

        mock_list_projects.return_value = [
            {"id": "summitflow", "name": "SummitFlow", "root_path": str(repo_root)},
        ]

        result = find_project_by_cwd("summitflow/backend/app")

        assert result == {
            "id": "summitflow",
            "name": "SummitFlow",
            "root_path": str(repo_root),
        }

    @patch("app.storage.projects.list_projects")
    def test_returns_none_when_no_root_contains_cwd(
        self,
        mock_list_projects: MagicMock,
        tmp_path: Path,
    ) -> None:
        from app.storage.projects import find_project_by_cwd

        repo_root = tmp_path / "summitflow"
        repo_root.mkdir()
        other_dir = tmp_path / "elsewhere"
        other_dir.mkdir()

        mock_list_projects.return_value = [
            {"id": "summitflow", "name": "SummitFlow", "root_path": str(repo_root)},
        ]

        assert find_project_by_cwd(str(other_dir)) is None

    @patch("app.storage.projects.get_project_root_path")
    def test_build_project_env_prepends_to_existing_pythonpath(
        self,
        mock_get_root: MagicMock,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        """When PYTHONPATH already exists, the new backend path is prepended.

        Arrange: a main repo with a .venv, a worktree with a backend/, and
        PYTHONPATH already set to an existing value in the environment.
        Act: call build_project_env() with the worktree as working_dir.
        Assert: PYTHONPATH starts with <working_dir>/backend and retains the
        pre-existing value after the colon separator.
        """
        from app.storage.projects import build_project_env

        # Arrange
        main_repo = tmp_path / "main-repo"
        _make_venv(main_repo)

        worktree = tmp_path / "worktrees" / "feature-branch"
        backend_dir = worktree / "backend"
        backend_dir.mkdir(parents=True)

        existing_pythonpath = "/some/existing/lib:/another/lib"

        mock_get_root.return_value = str(main_repo)

        env_before = os.environ.copy()
        env_before["PYTHONPATH"] = existing_pythonpath

        with patch.dict(os.environ, env_before, clear=True):
            # Act
            result = build_project_env(
                project_id="proj-abc123",
                working_dir=str(worktree),
            )

        # Assert
        assert "PYTHONPATH" in result
        pythonpath_entries = result["PYTHONPATH"].split(":")
        # New path must be first
        assert pythonpath_entries[0] == str(backend_dir)
        # Existing entries must still be present
        assert existing_pythonpath in result["PYTHONPATH"]

    @patch("app.storage.projects.get_project_root_path")
    def test_build_project_env_without_working_dir_omits_pythonpath(
        self,
        mock_get_root: MagicMock,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        """Backward compat: omitting working_dir does not inject PYTHONPATH.

        Arrange: a main repo with a .venv; no working_dir argument.
        Act: call build_project_env() with only a project_id.
        Assert: PYTHONPATH is absent from the returned env dict (or unchanged
        if it was already set in the environment).
        """
        from app.storage.projects import build_project_env

        # Arrange
        main_repo = tmp_path / "main-repo"
        _make_venv(main_repo)

        mock_get_root.return_value = str(main_repo)

        env_before = os.environ.copy()
        env_before.pop("PYTHONPATH", None)

        with patch.dict(os.environ, env_before, clear=True):
            # Act
            result = build_project_env(project_id="proj-abc123")

        # Assert
        assert "PYTHONPATH" not in result
