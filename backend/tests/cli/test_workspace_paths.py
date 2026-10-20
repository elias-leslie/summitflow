"""Tests for workspace-aware path helpers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _fresh_cli_paths(home: Path, **overrides: str) -> dict[str, str | None]:
    env = {key: value for key, value in os.environ.items()
           if key not in {"ST_WORKSPACES_ROOT", "ST_SCRATCH_ROOT", "XDG_CONFIG_HOME", "ST_BOOTSTRAP_OTHER"}}
    env.update(HOME=str(home), **overrides)
    result = subprocess.run(
        [sys.executable, "-c", "import cli; import json, os; "
         "from cli.lib.workspace_paths import get_workspaces_root; "
         "from app.utils.transient_scratch import SCRATCH_ROOT; "
         "print(json.dumps({'workspaces': str(get_workspaces_root()), 'scratch': str(SCRATCH_ROOT), "
         "'other': os.environ.get('ST_BOOTSTRAP_OTHER')}))"],
        cwd=Path(__file__).resolve().parents[2], env=env, text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("overrides", [{}, {"ST_SCRATCH_ROOT": "/explicit/scratch"},
                                     {"ST_WORKSPACES_ROOT": "/explicit/workspaces"}])
def test_fresh_cli_loads_installed_account_paths_before_imports(tmp_path: Path, overrides: dict[str, str]) -> None:
    config = tmp_path / ".config" / "environment.d"
    config.mkdir(parents=True)
    (config / "20-st-scratch.conf").write_text("# Account scratch\nST_SCRATCH_ROOT=/configured/scratch\n"
                                              "ST_BOOTSTRAP_OTHER=ignored\n")
    (config / "21-st-workspaces.conf").write_text('ST_WORKSPACES_ROOT="/configured/workspaces with spaces"\n')

    assert _fresh_cli_paths(tmp_path, **overrides) == {
        "workspaces": overrides.get("ST_WORKSPACES_ROOT", "/configured/workspaces with spaces"),
        "scratch": overrides.get("ST_SCRATCH_ROOT", "/configured/scratch"), "other": None,
    }


def test_fresh_cli_without_account_config_keeps_portable_defaults(tmp_path: Path) -> None:
    assert _fresh_cli_paths(tmp_path) == {
        "workspaces": str(tmp_path / ".local/share/summitflow/workspaces"), "scratch": "/srv/scratch", "other": None,
    }


def test_fresh_cli_account_paths_respect_xdg_config_and_do_not_execute_shell(tmp_path: Path) -> None:
    config_home = tmp_path / "config"
    config = config_home / "environment.d"
    config.mkdir(parents=True)
    marker = tmp_path / "executed"
    (config / "20-st-scratch.conf").write_text(f"ST_SCRATCH_ROOT=$(touch {marker})\n")
    (config / "21-st-workspaces.conf").write_text("ST_WORKSPACES_ROOT='/xdg/workspaces' # path only\n")

    assert _fresh_cli_paths(tmp_path, XDG_CONFIG_HOME=str(config_home)) == {
        "workspaces": "/xdg/workspaces", "scratch": "/srv/scratch", "other": None,
    }
    assert not marker.exists()


def test_get_projects_base_dir_prefers_btrfs_workspace(monkeypatch, tmp_path: Path) -> None:
    from cli.lib.workspace_paths import get_projects_base_dir

    workspace_root = tmp_path / "srv" / "workspaces"
    workspace_root.mkdir(parents=True)
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(workspace_root))

    result = get_projects_base_dir("summitflow")

    assert result == workspace_root / "projects" / "summitflow"
    assert result.is_dir()


def test_get_cache_base_dir_uses_btrfs_workspace(monkeypatch, tmp_path: Path) -> None:
    from cli.lib.workspace_paths import get_cache_base_dir

    workspace_root = tmp_path / "srv" / "workspaces"
    workspace_root.mkdir(parents=True)
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(workspace_root))

    result = get_cache_base_dir("uv")

    assert result == workspace_root / "cache" / "uv"
    assert result.is_dir()
