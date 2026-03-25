"""Tests for Btrfs-aware worktree creation."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_create_worktree_precreates_btrfs_subvolume_for_workspace_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.worktree import WorktreeInfo, create_worktree

    lane_base = tmp_path / "srv" / "workspaces" / "lanes" / "summitflow"
    worktree_path = lane_base / "task-abc"
    repo_root = tmp_path / "repo"
    calls: list[list[str]] = []

    monkeypatch.setattr("cli.lib.worktree.workspaces_root_available", lambda: True)
    monkeypatch.setattr("cli.lib.worktree.get_lanes_base_dir", lambda project_id=None: lane_base)
    monkeypatch.setattr(
        "cli.lib.worktree.get_worktree_path",
        lambda task_id, project_id=None: worktree_path,
    )
    monkeypatch.setattr("cli.lib.worktree.get_repo_root", lambda cwd=None: repo_root)
    monkeypatch.setattr("cli.lib.worktree.get_project_cwd", lambda project_id: None)
    monkeypatch.setattr("cli.lib.worktree.verify_base_branch", lambda base_branch, repo_root: None)
    monkeypatch.setattr("cli.lib.worktree.symlink_gitignored_deps", lambda repo_root, wt: None)
    monkeypatch.setattr("cli.lib.worktree.get_worktree_info", lambda task_id, project_id=None: None)

    def _fake_btrfs(args: list[str]) -> None:
        calls.append(args)
        if args[:2] == ["subvolume", "create"]:
            worktree_path.mkdir(parents=True, exist_ok=False)

    def _fake_create_branch(
        path: Path, branch_name: str, base_branch: str, repo_root: Path, task_id: str
    ) -> None:
        calls.append(["git-worktree-add", str(path)])
        assert path.exists()
        assert branch_name == "task-abc/main"

    monkeypatch.setattr("cli.lib.worktree._run_btrfs", _fake_btrfs)
    monkeypatch.setattr("cli.lib.worktree.create_worktree_branch", _fake_create_branch)

    info = create_worktree("task-abc", "main", "summitflow")

    assert isinstance(info, WorktreeInfo)
    assert info.path == worktree_path
    assert calls[0] == ["subvolume", "create", str(worktree_path)]
    assert calls[1] == ["git-worktree-add", str(worktree_path)]


def test_create_worktree_removes_created_subvolume_if_git_add_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.worktree import WorktreeError, create_worktree

    lane_base = tmp_path / "srv" / "workspaces" / "lanes" / "summitflow"
    worktree_path = lane_base / "task-fail"
    repo_root = tmp_path / "repo"
    calls: list[list[str]] = []

    monkeypatch.setattr("cli.lib.worktree.workspaces_root_available", lambda: True)
    monkeypatch.setattr("cli.lib.worktree.get_lanes_base_dir", lambda project_id=None: lane_base)
    monkeypatch.setattr(
        "cli.lib.worktree.get_worktree_path",
        lambda task_id, project_id=None: worktree_path,
    )
    monkeypatch.setattr("cli.lib.worktree.get_repo_root", lambda cwd=None: repo_root)
    monkeypatch.setattr("cli.lib.worktree.get_project_cwd", lambda project_id: None)
    monkeypatch.setattr("cli.lib.worktree.verify_base_branch", lambda base_branch, repo_root: None)
    monkeypatch.setattr("cli.lib.worktree.symlink_gitignored_deps", lambda repo_root, wt: None)
    monkeypatch.setattr("cli.lib.worktree.get_worktree_info", lambda task_id, project_id=None: None)

    def _fake_btrfs(args: list[str]) -> None:
        calls.append(args)
        if args[:2] == ["subvolume", "create"]:
            worktree_path.mkdir(parents=True, exist_ok=False)
        elif args[:2] == ["subvolume", "delete"] and worktree_path.exists():
            worktree_path.rmdir()

    def _failing_create_branch(
        path: Path, branch_name: str, base_branch: str, repo_root: Path, task_id: str
    ) -> None:
        raise WorktreeError("boom")

    monkeypatch.setattr("cli.lib.worktree._run_btrfs", _fake_btrfs)
    monkeypatch.setattr("cli.lib.worktree.create_worktree_branch", _failing_create_branch)

    with pytest.raises(WorktreeError, match="boom"):
        create_worktree("task-fail", "main", "summitflow")

    assert ["subvolume", "create", str(worktree_path)] in calls
    assert ["subvolume", "delete", str(worktree_path)] in calls
    assert not worktree_path.exists()


def test_force_remove_worktree_cleans_empty_lane_left_after_git_remove_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.worktree_helpers import force_remove_worktree

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree_path = tmp_path / "srv" / "workspaces" / "lanes" / "summitflow" / "task-empty"
    worktree_path.mkdir(parents=True)
    calls: list[tuple[str, ...]] = []

    def _fake_run_git(args: list[str], cwd: Path, check: bool = True):
        calls.append(tuple(args))
        assert cwd == repo_root
        assert check in (True, False)

    monkeypatch.setattr("cli.lib.worktree_helpers.run_git", _fake_run_git)

    force_remove_worktree(worktree_path, repo_root)

    assert ("worktree", "remove", str(worktree_path), "--force") in calls
    assert ("worktree", "prune") in calls
    assert not worktree_path.exists()
