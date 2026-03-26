"""Tests for Btrfs-aware worktree creation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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


def test_remove_worktree_prunes_registration_and_branch_when_path_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.worktree import remove_worktree

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree_path = tmp_path / "srv" / "workspaces" / "lanes" / "agent-hub" / "task-missing"
    calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        "cli.lib.worktree.get_worktree_path",
        lambda task_id, project_id=None: worktree_path,
    )
    monkeypatch.setattr("cli.lib.worktree.get_project_cwd", lambda project_id: repo_root)
    monkeypatch.setattr("cli.lib.worktree.get_repo_root", lambda cwd=None: repo_root)

    def _fake_run_git(args: list[str], cwd: Path, check: bool = True):
        calls.append(tuple(args))
        assert cwd == repo_root
        assert check in (True, False)

    monkeypatch.setattr("cli.lib.worktree.run_git", _fake_run_git)

    removed = remove_worktree("task-missing", delete_branch=True, project_id="agent-hub")

    assert removed is True
    assert ("worktree", "prune") in calls
    assert ("branch", "-D", "task-missing/main") in calls


def test_merge_task_branch_reconciles_git_state_even_without_live_worktree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.checkpoint_branches import merge_task_branch

    calls: list[tuple[str, ...]] = []

    monkeypatch.setattr("app.storage.tasks.get_task", lambda task_id: {"id": task_id, "status": "pending"})
    monkeypatch.setattr(
        "cli.lib.checkpoint_branches.load_snapshot_meta",
        lambda task_id: SimpleNamespace(project_id="agent-hub", base_branch="main"),
    )
    monkeypatch.setattr("cli.lib.checkpoint_branches._get_repo_cwd", lambda project_id: "/repo")
    monkeypatch.setattr("cli.lib.checkpoint_branches._get_current_branch", lambda cwd=None: "main")
    monkeypatch.setattr("cli.lib.worktree.get_worktree_info", lambda task_id, project_id=None: None)

    def _fake_run_git(args: list[str], cwd: str | None = None, check: bool = True):
        calls.append(tuple(args))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    remove_calls: list[tuple[str, bool, str | None]] = []

    monkeypatch.setattr("cli.lib.checkpoint_branches._run_git", _fake_run_git)
    monkeypatch.setattr(
        "cli.lib.worktree.remove_worktree",
        lambda task_id, delete_branch, project_id=None: remove_calls.append((task_id, delete_branch, project_id)) or True,
    )

    assert merge_task_branch("task-ghost", project_id="agent-hub") is True
    assert ("git", "merge", "--no-ff", "task-ghost/main", "-m", "Merge task task-ghost") in calls
    assert remove_calls == [("task-ghost", False, "agent-hub")]
