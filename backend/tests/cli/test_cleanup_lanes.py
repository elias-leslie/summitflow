"""Tests for Btrfs lane cleanup (st cleanup lanes)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.commands.cleanup import app
from cli.lib.worktree_git import WorktreeError

runner = CliRunner()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@t"},
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-b", "main")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")


def _fake_btrfs(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    del cwd
    if args[:2] == ["subvolume", "create"]:
        Path(args[2]).mkdir(parents=True, exist_ok=False)
    elif args[:2] == ["subvolume", "delete"]:
        shutil.rmtree(args[2], ignore_errors=True)
    elif args[:2] == ["property", "set"]:
        pass  # no-op for ro property
    return subprocess.CompletedProcess(["btrfs", *args], 0, "", "")


def _fake_snapshot_subvolume(source: Path, destination: Path, *, readonly: bool) -> None:
    del readonly
    shutil.copytree(source, destination, symlinks=True)


def _fake_delete_subvolume(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _patch_fake_btrfs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cli.lib.quick_snapshots._require_btrfs_subvolume", lambda path: None)
    monkeypatch.setattr("cli.lib.quick_snapshots._snapshot_subvolume", _fake_snapshot_subvolume)
    monkeypatch.setattr("cli.lib.quick_snapshots._delete_subvolume", _fake_delete_subvolume)
    monkeypatch.setattr("cli.lib.quick_snapshots._btrfs", _fake_btrfs)


def _setup_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Create a fake workspace with a canonical repo and return (workspaces_root, canonical)."""
    home = tmp_path / "home"
    home.mkdir()
    workspaces_root = tmp_path / "workspaces"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(workspaces_root))
    _patch_fake_btrfs(monkeypatch)

    canonical = workspaces_root / "projects" / "summitflow"
    canonical.mkdir(parents=True)
    _init_repo(canonical)
    return workspaces_root, canonical


def _create_lane(canonical: Path, workspaces_root: Path, lane_name: str) -> Path:
    """Create a lane as a git worktree under the workspace."""
    lane = workspaces_root / "lanes" / "summitflow" / lane_name
    lane.parent.mkdir(parents=True, exist_ok=True)
    _git(canonical, "worktree", "add", str(lane), "-b", f"{lane_name}/main", "main")
    return lane


def _create_snapshot_for_lane(workspaces_root: Path, lane_name: str, snap_id: str) -> Path:
    """Create a fake snapshot directory for a lane."""
    snap_dir = workspaces_root / ".snapshots" / "summitflow" / "lanes" / lane_name / snap_id
    snap_dir.mkdir(parents=True)
    (snap_dir / "README.md").write_text("snapshot\n", encoding="utf-8")
    return snap_dir


def _create_checkpoint_meta(tmp_path: Path, task_id: str, worktree_path: Path) -> Path:
    checkpoint_dir = tmp_path / "home" / ".local" / "share" / "st" / "checkpoints" / "summitflow"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    meta_path = checkpoint_dir / f"{task_id}.meta.json"
    meta_path.write_text(
        (
            "{\n"
            f'  "task_id": "{task_id}",\n'
            '  "project_id": "summitflow",\n'
            '  "base_branch": "main",\n'
            '  "created_at": "2026-03-21T00:00:00+00:00",\n'
            '  "claimed_by": "Test",\n'
            f'  "worktree_path": "{worktree_path}",\n'
            '  "backend_port": 8170,\n'
            '  "frontend_port": 3170\n'
            "}\n"
        ),
        encoding="utf-8",
    )
    return meta_path


class TestInspectLane:
    def test_inspect_lane_with_snapshots_and_worktree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cli.lib.quick_snapshots import inspect_lane

        workspaces_root, canonical = _setup_workspace(tmp_path, monkeypatch)
        lane = _create_lane(canonical, workspaces_root, "test-lane")
        _create_snapshot_for_lane(workspaces_root, "test-lane", "snap-001")
        _create_snapshot_for_lane(workspaces_root, "test-lane", "snap-002")

        result = inspect_lane("summitflow", "test-lane")

        assert result.project_id == "summitflow"
        assert result.lane_name == "test-lane"
        assert result.lane_path == lane
        assert result.is_git_worktree is True
        assert result.branch == "test-lane/main"
        assert len(result.snapshot_paths) == 2
        assert result.snapshot_dir is not None
        assert result.total_items == 3  # 2 snapshots + 1 lane

    def test_inspect_lane_without_snapshots(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cli.lib.quick_snapshots import inspect_lane

        workspaces_root, canonical = _setup_workspace(tmp_path, monkeypatch)
        _create_lane(canonical, workspaces_root, "bare-lane")

        result = inspect_lane("summitflow", "bare-lane")

        assert result.branch == "bare-lane/main"
        assert result.snapshot_paths == []
        assert result.snapshot_dir is None
        assert result.total_items == 1

    def test_inspect_nonexistent_lane_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cli.lib.quick_snapshots import SnapshotError, inspect_lane

        _setup_workspace(tmp_path, monkeypatch)

        with pytest.raises(SnapshotError, match="Lane does not exist"):
            inspect_lane("summitflow", "ghost-lane")


class TestDeleteLane:
    def test_delete_lane_removes_snapshots_lane_and_manifest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cli.lib.quick_snapshots import delete_lane, inspect_lane

        workspaces_root, canonical = _setup_workspace(tmp_path, monkeypatch)
        lane = _create_lane(canonical, workspaces_root, "doomed-lane")
        snap = _create_snapshot_for_lane(workspaces_root, "doomed-lane", "snap-001")

        # Create a manifest dir
        manifest_dir = (
            tmp_path / "home" / ".local" / "share" / "st" / "snaps"
            / "summitflow" / "lane-doomed-lane"
        )
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "manifest.json").write_text("[]", encoding="utf-8")
        checkpoint_meta = _create_checkpoint_meta(tmp_path, "task-doomed-lane", lane)

        inspection = inspect_lane("summitflow", "doomed-lane")
        monkeypatch.chdir(tmp_path)  # Ensure we're outside the lane
        delete_lane(inspection)

        assert not lane.exists(), "Lane subvolume should be deleted"
        assert not snap.exists(), "Snapshot should be deleted"
        assert not manifest_dir.exists(), "Manifest dir should be deleted"
        assert not checkpoint_meta.exists(), "Checkpoint metadata should be deleted"

        # Git worktree registration should be cleaned up
        wt_list = _git(canonical, "worktree", "list", "--porcelain").stdout
        assert "doomed-lane" not in wt_list
        branch_list = _git(canonical, "branch", "--list", "doomed-lane/main").stdout
        assert not branch_list.strip(), "Lane branch should be deleted"

    def test_delete_lane_without_snapshots(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cli.lib.quick_snapshots import delete_lane, inspect_lane

        workspaces_root, canonical = _setup_workspace(tmp_path, monkeypatch)
        lane = _create_lane(canonical, workspaces_root, "simple-lane")

        inspection = inspect_lane("summitflow", "simple-lane")
        monkeypatch.chdir(tmp_path)
        delete_lane(inspection)

        assert not lane.exists()

    def test_delete_lane_raises_when_git_worktree_removal_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cli.lib.quick_snapshots import SnapshotError, delete_lane, inspect_lane

        workspaces_root, canonical = _setup_workspace(tmp_path, monkeypatch)
        lane = _create_lane(canonical, workspaces_root, "broken-lane")
        snap = _create_snapshot_for_lane(workspaces_root, "broken-lane", "snap-001")

        def _boom(worktree_path: Path, repo_root: Path) -> None:
            raise WorktreeError("git worktree remove failed")

        monkeypatch.setattr("cli.lib.quick_snapshots.force_remove_worktree", _boom)

        inspection = inspect_lane("summitflow", "broken-lane")
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SnapshotError, match="Failed to remove git worktree registration"):
            delete_lane(inspection)

        assert lane.exists(), "Lane should remain when worktree removal fails"
        assert snap.exists(), "Snapshots should remain when worktree removal fails"
        branch_list = _git(canonical, "branch", "--list", "broken-lane/main").stdout
        assert branch_list.strip(), "Lane branch should remain when cleanup aborts early"

class TestOrphanedSnapshotDirs:
    def test_find_orphaned_snapshot_dirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cli.lib.quick_snapshots import find_orphaned_snapshot_dirs

        workspaces_root, canonical = _setup_workspace(tmp_path, monkeypatch)

        # Create a lane that still exists
        _create_lane(canonical, workspaces_root, "alive-lane")
        _create_snapshot_for_lane(workspaces_root, "alive-lane", "snap-001")

        # Create orphaned snapshots (lane doesn't exist)
        _create_snapshot_for_lane(workspaces_root, "dead-lane", "snap-001")
        _create_snapshot_for_lane(workspaces_root, "dead-lane", "snap-002")

        orphans = find_orphaned_snapshot_dirs("summitflow")

        assert len(orphans) == 1
        assert orphans[0].lane_name == "dead-lane"
        assert len(orphans[0].snapshot_paths) == 2

    def test_delete_orphaned_snapshots(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cli.lib.quick_snapshots import delete_orphaned_snapshots, find_orphaned_snapshot_dirs

        workspaces_root, _ = _setup_workspace(tmp_path, monkeypatch)

        snap1 = _create_snapshot_for_lane(workspaces_root, "gone-lane", "snap-001")
        snap_dir = snap1.parent

        # Create a manifest dir
        manifest_dir = (
            tmp_path / "home" / ".local" / "share" / "st" / "snaps"
            / "summitflow" / "lane-gone-lane"
        )
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "manifest.json").write_text("[]", encoding="utf-8")

        orphans = find_orphaned_snapshot_dirs("summitflow")
        assert len(orphans) == 1

        delete_orphaned_snapshots(orphans[0])

        assert not snap1.exists()
        assert not snap_dir.exists()
        assert not manifest_dir.exists()

    def test_no_orphans_when_lanes_exist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cli.lib.quick_snapshots import find_orphaned_snapshot_dirs

        workspaces_root, canonical = _setup_workspace(tmp_path, monkeypatch)
        _create_lane(canonical, workspaces_root, "active-lane")
        _create_snapshot_for_lane(workspaces_root, "active-lane", "snap-001")

        orphans = find_orphaned_snapshot_dirs("summitflow")
        assert orphans == []


class TestDeleteLaneSnapshotDir:
    def test_delete_lane_cleans_snapshot_parent_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cli.lib.quick_snapshots import delete_lane, inspect_lane

        workspaces_root, canonical = _setup_workspace(tmp_path, monkeypatch)
        _create_lane(canonical, workspaces_root, "snap-lane")
        _create_snapshot_for_lane(workspaces_root, "snap-lane", "snap-001")
        snap_parent = workspaces_root / ".snapshots" / "summitflow" / "lanes" / "snap-lane"
        assert snap_parent.exists()

        inspection = inspect_lane("summitflow", "snap-lane")
        monkeypatch.chdir(tmp_path)
        delete_lane(inspection)

        assert not snap_parent.exists(), "Empty snapshot parent dir should be removed"


class TestCleanupLanesCommand:
    def test_cleanup_lanes_default_preview_only_lists_orphaned_lanes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        workspaces_root, canonical = _setup_workspace(tmp_path, monkeypatch)
        _create_lane(canonical, workspaces_root, "kept-lane")

        orphan_lane = workspaces_root / "lanes" / "summitflow" / "orphan-lane"
        orphan_lane.mkdir(parents=True)

        monkeypatch.setattr("cli.commands.cleanup.get_project_id", lambda all_projects=False: "summitflow")
        monkeypatch.setattr("cli.lib.confirm_token.generate_token", lambda key: "deadbeef")

        result = runner.invoke(app, ["lanes"])

        assert result.exit_code == 0
        assert "orphan-lane" in result.output
        assert "kept-lane" not in result.output
        assert "DELETE orphaned target(s)" in result.output

    def test_cleanup_lanes_explicit_target_can_preview_git_worktree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        workspaces_root, canonical = _setup_workspace(tmp_path, monkeypatch)
        _create_lane(canonical, workspaces_root, "kept-lane")

        monkeypatch.setattr("cli.commands.cleanup.get_project_id", lambda all_projects=False: "summitflow")
        monkeypatch.setattr("cli.lib.confirm_token.generate_token", lambda key: "deadbeef")

        result = runner.invoke(app, ["lanes", "kept-lane"])

        assert result.exit_code == 0
        assert "kept-lane" in result.output
        assert "[git-worktree]" in result.output
        assert "DELETE explicit lane target(s)" in result.output

    def test_cleanup_lanes_preview_includes_stale_checkpoint_without_lane(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        workspaces_root, _canonical = _setup_workspace(tmp_path, monkeypatch)
        stale_path = workspaces_root / "lanes" / "summitflow" / "task-stale"
        _create_checkpoint_meta(tmp_path, "task-stale", stale_path)

        monkeypatch.setattr("cli.commands.cleanup.get_project_id", lambda all_projects=False: "summitflow")
        monkeypatch.setattr("cli.lib.confirm_token.generate_token", lambda key: "deadbeef")

        result = runner.invoke(app, ["lanes"])

        assert result.exit_code == 0
        assert "STALE-CHECKPOINT summitflow/task-stale" in result.output

    def test_cleanup_lanes_deletes_stale_checkpoint_without_lane(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        workspaces_root, _canonical = _setup_workspace(tmp_path, monkeypatch)
        stale_path = workspaces_root / "lanes" / "summitflow" / "task-stale"
        meta_path = _create_checkpoint_meta(tmp_path, "task-stale", stale_path)

        monkeypatch.setattr("cli.commands.cleanup.get_project_id", lambda all_projects=False: "summitflow")
        monkeypatch.setattr("cli.lib.confirm_token.validate_token", lambda key, token: True)

        result = runner.invoke(app, ["lanes", "--confirm", "deadbeef"])

        assert result.exit_code == 0
        assert "Deleted stale checkpoint: summitflow/task-stale" in result.output
        assert not meta_path.exists()
