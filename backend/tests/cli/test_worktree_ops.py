"""Tests for workspace-aware worktree operation helpers."""

from __future__ import annotations

from pathlib import Path


def test_get_project_cwd_prefers_current_btrfs_project_root(monkeypatch, tmp_path: Path) -> None:
    from cli.lib.worktree_ops import get_project_cwd

    workspaces_root = tmp_path / "workspaces"
    project_root = workspaces_root / "projects" / "summitflow"
    configured_root = tmp_path / "configured" / "summitflow"
    project_root.mkdir(parents=True)
    configured_root.mkdir(parents=True)

    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(workspaces_root))
    monkeypatch.chdir(project_root)
    monkeypatch.setattr("cli.lib.worktree_ops.get_repo_root", lambda cwd=None: project_root)
    monkeypatch.setattr(
        "app.storage.projects.get_project_root_path",
        lambda project_id: str(configured_root),
    )

    assert get_project_cwd("summitflow") == project_root.resolve()


def test_get_project_cwd_falls_back_to_configured_root_outside_btrfs_project(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from cli.lib.worktree_ops import get_project_cwd

    workspaces_root = tmp_path / "workspaces"
    project_root = workspaces_root / "projects" / "summitflow"
    outside_repo = tmp_path / "outside" / "summitflow"
    configured_root = tmp_path / "configured" / "summitflow"
    project_root.mkdir(parents=True)
    outside_repo.mkdir(parents=True)
    configured_root.mkdir(parents=True)

    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(workspaces_root))
    monkeypatch.chdir(outside_repo)
    monkeypatch.setattr("cli.lib.worktree_ops.get_repo_root", lambda cwd=None: outside_repo)
    monkeypatch.setattr(
        "app.storage.projects.get_project_root_path",
        lambda project_id: str(configured_root),
    )

    assert get_project_cwd("summitflow") == configured_root
