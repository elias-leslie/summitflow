"""Tests for workspace-aware worktree path helpers."""

from __future__ import annotations

from pathlib import Path


def test_get_worktrees_base_dir_prefers_btrfs_workspace(monkeypatch, tmp_path: Path) -> None:
    from cli.lib.worktree_paths import get_worktrees_base_dir

    workspace_root = tmp_path / "srv" / "workspaces"
    workspace_root.mkdir(parents=True)
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(workspace_root))

    result = get_worktrees_base_dir("summitflow")

    assert result == workspace_root / "lanes" / "summitflow"
    assert result.is_dir()


def test_get_worktrees_base_dir_falls_back_to_legacy_path(monkeypatch, tmp_path: Path) -> None:
    from cli.lib.worktree_paths import get_worktrees_base_dir

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(tmp_path / "missing-workspaces"))

    result = get_worktrees_base_dir("summitflow")

    assert result == home / ".local" / "share" / "st" / "worktrees" / "summitflow"
    assert result.is_dir()


def test_get_cache_base_dir_uses_btrfs_workspace(monkeypatch, tmp_path: Path) -> None:
    from cli.lib.worktree_paths import get_cache_base_dir

    workspace_root = tmp_path / "srv" / "workspaces"
    workspace_root.mkdir(parents=True)
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(workspace_root))

    result = get_cache_base_dir("uv")

    assert result == workspace_root / "cache" / "uv"
    assert result.is_dir()
