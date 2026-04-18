"""Tests for CLI project detection across checkouts and detached checkouts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from cli import config as config_mod


class TestProjectDetection:
    def test_detect_project_from_local_index_skips_api_lookup(self, tmp_path) -> None:
        """Repo-local `.index.yaml` should avoid the `/projects` round-trip entirely."""
        repo_root = tmp_path / "summitflow"
        backend_dir = repo_root / "backend"
        backend_dir.mkdir(parents=True)
        (repo_root / ".index.yaml").write_text("project: summitflow\n")

        with (
            patch("cli.config.Path.cwd", return_value=backend_dir.resolve()),
            patch.object(config_mod, "_fetch_projects_with_retry") as fetch_projects,
        ):
            project_id, root_path = config_mod._detect_project_from_cwd("http://localhost:8001/api")

        assert project_id == "summitflow"
        assert root_path == str(repo_root.resolve())
        fetch_projects.assert_not_called()

    def test_detect_project_from_canonical_index_skips_api_lookup(self, tmp_path) -> None:
        """Detached/helper checkouts should use the canonical repo root metadata when available."""
        repo_root = tmp_path / "summitflow"
        repo_root.mkdir()
        (repo_root / ".index.yaml").write_text("project: summitflow\n")
        detached_checkout = tmp_path / "summitflow-merge-main"
        detached_checkout.mkdir()

        with (
            patch("cli.config.Path.cwd", return_value=detached_checkout.resolve()),
            patch.object(config_mod, "canonical_repo_root", return_value=repo_root.resolve()),
            patch.object(config_mod, "_fetch_projects_with_retry") as fetch_projects,
        ):
            project_id, root_path = config_mod._detect_project_from_cwd("http://localhost:8001/api")

        assert project_id == "summitflow"
        assert root_path == str(repo_root.resolve())
        fetch_projects.assert_not_called()

    def test_detect_project_from_cwd_detached_checkout_returns_canonical_root(self) -> None:
        """Detached helper checkouts should resolve to the canonical project root."""
        fake_home = Path("/home/testuser")
        fake_root = str(fake_home / "summitflow")
        projects = [
            {
                "id": "summitflow",
                "root_path": fake_root,
            }
        ]
        cwd = Path("/tmp/summitflow-merge-main").resolve()

        with (
            patch.object(config_mod, "_fetch_projects_with_retry", return_value=projects),
            patch.object(
                config_mod,
                "canonical_repo_root",
                return_value=Path(fake_root),
            ),
            patch("cli.config.Path.cwd", return_value=cwd),
        ):
            project_id, root_path = config_mod._detect_project_from_cwd("http://localhost:8001/api")

        assert project_id == "summitflow"
        assert root_path == fake_root

    def test_detect_project_from_cwd_direct_match_returns_checkout_path(self) -> None:
        """Normal repo-root detection should keep using the current checkout path."""
        fake_home = Path("/home/testuser")
        fake_root = str(fake_home / "summitflow")
        projects = [
            {
                "id": "summitflow",
                "root_path": fake_root,
            }
        ]
        cwd = Path(fake_root + "/backend").resolve()

        with (
            patch.object(config_mod, "_fetch_projects_with_retry", return_value=projects),
            patch.object(config_mod, "canonical_repo_root", return_value=None),
            patch("cli.config.Path.cwd", return_value=cwd),
        ):
            project_id, root_path = config_mod._detect_project_from_cwd("http://localhost:8001/api")

        assert project_id == "summitflow"
        assert root_path == fake_root

    def test_detect_project_from_cwd_returns_none_when_cwd_deleted(self) -> None:
        """Deleted checkout dir must not crash — returns (None, None) without calling the API."""
        with (
            patch("cli.config.Path.cwd", side_effect=FileNotFoundError("deleted")),
            patch.object(config_mod, "_fetch_projects_with_retry") as fetch_projects,
        ):
            project_id, root_path = config_mod._detect_project_from_cwd("http://localhost:8001/api")

        assert project_id is None
        assert root_path is None
        fetch_projects.assert_not_called()

    def test_detect_project_from_cwd_returns_none_on_oserror(self) -> None:
        """Any OSError on cwd (e.g. PermissionError) must be handled gracefully."""
        with (
            patch("cli.config.Path.cwd", side_effect=OSError("permission denied")),
            patch.object(config_mod, "_fetch_projects_with_retry") as fetch_projects,
        ):
            project_id, root_path = config_mod._detect_project_from_cwd("http://localhost:8001/api")

        assert project_id is None
        assert root_path is None
        fetch_projects.assert_not_called()

    def test_project_override_bypasses_cwd_when_cwd_deleted(self) -> None:
        """-P flag (project override) must work even when the cwd no longer exists."""
        config_mod.set_project_override("summitflow")
        try:
            with patch("cli.config.Path.cwd", side_effect=FileNotFoundError("deleted")):
                project_id, _root_path, source = config_mod._resolve_project("http://localhost:8001/api")
        finally:
            config_mod.set_project_override(None)

        assert project_id == "summitflow"
        assert source == "flag"
