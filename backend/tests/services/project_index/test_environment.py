"""Environment detection for `.index.yaml`."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from app.services.project_index.environment import _read_node_info, get_environment


def test_read_node_info_prefers_package_manager_field(tmp_path: Path) -> None:
    """Package manager should come from package.json when explicitly pinned."""
    package_json = tmp_path / "package.json"
    package_json.write_text(json.dumps({"engines": {"node": "24"}, "packageManager": "pnpm@10.28.0"}))

    assert _read_node_info(package_json, tmp_path) == {"node_version": "24", "package_manager": "pnpm"}


def test_read_node_info_fallback_to_lockfile_detection(tmp_path: Path) -> None:
    """When packageManager field is missing, fallback to lockfile detection."""
    package_json = tmp_path / "package.json"
    package_json.write_text(json.dumps({"engines": {"node": "20"}}))
    (tmp_path / "pnpm-lock.yaml").touch()

    assert _read_node_info(package_json, tmp_path) == {"node_version": "20", "package_manager": "pnpm"}


def test_read_node_info_raw_package_manager_without_version(tmp_path: Path) -> None:
    """When packageManager has no @version suffix, ensure it returns that raw value."""
    package_json = tmp_path / "package.json"
    package_json.write_text(json.dumps({"engines": {"node": "18"}, "packageManager": "yarn"}))

    assert _read_node_info(package_json, tmp_path) == {"node_version": "18", "package_manager": "yarn"}


def test_get_environment_reads_backend_and_frontend_manifests(tmp_path: Path) -> None:
    (tmp_path / "backend" / ".venv").mkdir(parents=True)
    (tmp_path / "backend" / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.13"\n')
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text(json.dumps({"engines": {"node": "24"}}))

    with patch("app.services.project_index.environment.get_project_root", return_value=str(tmp_path)):
        env = get_environment("demo")

    assert env == {
        "python_version": ">=3.13",
        "venv_path": "backend/.venv",
        "node_version": "24",
        "package_manager": "npm",
    }


def test_get_environment_without_root_is_empty() -> None:
    with patch("app.services.project_index.environment.get_project_root", return_value=None):
        assert get_environment("demo") == {}
