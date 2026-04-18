"""Tests for workspace-aware path helpers."""

from __future__ import annotations

from pathlib import Path


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
