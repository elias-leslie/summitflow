"""Tests for Btrfs-backed snapshot CLI support."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

runner = CliRunner()


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env=merged_env,
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Snapshot Tester")
    _git(repo, "config", "user.email", "snapshot@test.local")
    (repo / ".index.yaml").write_text("project: summitflow\n", encoding="utf-8")
    (repo / ".gitignore").write_text("ignored.log\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")


def _read_index_file(repo: Path, path: str) -> str:
    return _git(repo, "show", f":{path}").stdout


def _fake_snapshot_subvolume(source: Path, destination: Path, *, readonly: bool) -> None:
    del readonly
    shutil.copytree(source, destination, symlinks=True)


def _fake_delete_subvolume(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _fake_btrfs(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    del cwd
    if args[:2] == ["subvolume", "create"]:
        Path(args[2]).mkdir(parents=True, exist_ok=False)
    elif args[:2] == ["subvolume", "delete"]:
        shutil.rmtree(args[2], ignore_errors=True)
    return subprocess.CompletedProcess(["btrfs", *args], 0, "", "")


def _patch_fake_btrfs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cli.lib.quick_snapshots._require_btrfs_subvolume", lambda path: None)
    monkeypatch.setattr("cli.lib.quick_snapshots._snapshot_subvolume", _fake_snapshot_subvolume)
    monkeypatch.setattr("cli.lib.quick_snapshots._delete_subvolume", _fake_delete_subvolume)
    monkeypatch.setattr("cli.lib.quick_snapshots._btrfs", _fake_btrfs)


def _create_lane_repo(workspaces_root: Path, lane_name: str = "task-123") -> tuple[Path, Path]:
    canonical = workspaces_root / "canonical"
    canonical.mkdir(parents=True)
    _init_repo(canonical)
    lane = workspaces_root / "lanes" / "summitflow" / lane_name
    lane.parent.mkdir(parents=True, exist_ok=True)
    _git(canonical, "worktree", "add", str(lane), "-b", f"{lane_name}/main", "main")
    return canonical, lane


def _create_project_repo(workspaces_root: Path) -> Path:
    project = workspaces_root / "projects" / "summitflow"
    project.mkdir(parents=True)
    _init_repo(project)
    return project


def test_lane_snapshot_round_trip_restores_tracked_staged_untracked_and_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.quick_snapshots import capture_snapshot, list_snapshots, restore_snapshot

    workspaces_root = tmp_path / "workspaces"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(workspaces_root))
    _patch_fake_btrfs(monkeypatch)
    _, lane = _create_lane_repo(workspaces_root)

    tracked = lane / "tracked.txt"
    tracked.write_text("two\n", encoding="utf-8")
    _git(lane, "add", "tracked.txt")
    tracked.write_text("three\n", encoding="utf-8")
    (lane / "note.txt").write_text("note-before\n", encoding="utf-8")
    (lane / "ignored.log").write_text("ignored-before\n", encoding="utf-8")

    monkeypatch.chdir(lane)
    snapshot = capture_snapshot("before-refactor", project_id="summitflow")

    tracked.write_text("four\n", encoding="utf-8")
    _git(lane, "add", "tracked.txt")
    tracked.write_text("five\n", encoding="utf-8")
    (lane / "note.txt").unlink()
    (lane / "extra.txt").write_text("extra\n", encoding="utf-8")
    (lane / "ignored.log").write_text("ignored-after\n", encoding="utf-8")

    restored = restore_snapshot(snapshot.id, project_id="summitflow")

    assert restored.id == snapshot.id
    assert restored.scope_type == "lane"
    assert tracked.read_text(encoding="utf-8") == "three\n"
    assert _read_index_file(lane, "tracked.txt") == "two\n"
    assert (lane / "note.txt").read_text(encoding="utf-8") == "note-before\n"
    assert not (lane / "extra.txt").exists()
    assert (lane / "ignored.log").read_text(encoding="utf-8") == "ignored-before\n"

    listed = list_snapshots(project_id="summitflow")
    assert [entry.id for entry in listed] == [snapshot.id]
    assert listed[0].name == "before-refactor"
    assert listed[0].scope_type == "lane"


def test_recover_snapshot_creates_sibling_lane_without_mutating_current_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.quick_snapshots import capture_snapshot, recover_snapshot

    workspaces_root = tmp_path / "workspaces"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(workspaces_root))
    _patch_fake_btrfs(monkeypatch)
    _, lane = _create_lane_repo(workspaces_root, lane_name="task-abc")

    tracked = lane / "tracked.txt"
    tracked.write_text("two\n", encoding="utf-8")
    _git(lane, "add", "tracked.txt")
    tracked.write_text("three\n", encoding="utf-8")
    (lane / "note.txt").write_text("note-before\n", encoding="utf-8")

    monkeypatch.chdir(lane)
    snapshot = capture_snapshot("before-recover", project_id="summitflow")

    tracked.write_text("four\n", encoding="utf-8")
    _git(lane, "add", "tracked.txt")
    tracked.write_text("five\n", encoding="utf-8")
    (lane / "note.txt").unlink()
    (lane / "extra.txt").write_text("extra\n", encoding="utf-8")

    recovered = recover_snapshot(snapshot.id, project_id="summitflow", name="inspection")
    recovery_path = Path(recovered.recovery_path or "")

    assert recovered.scope_type == "lane"
    assert recovered.recovery_branch == "recover-task-abc-inspection"
    assert recovery_path == workspaces_root / "lanes" / "summitflow" / "inspection"
    assert tracked.read_text(encoding="utf-8") == "five\n"
    assert (lane / "extra.txt").exists()
    assert (recovery_path / "tracked.txt").read_text(encoding="utf-8") == "three\n"
    assert _read_index_file(recovery_path, "tracked.txt") == "two\n"
    assert (recovery_path / "note.txt").read_text(encoding="utf-8") == "note-before\n"
    assert not (recovery_path / "extra.txt").exists()


def test_project_snapshot_recover_creates_sibling_project_copy_and_blocks_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.quick_snapshots import (
        SnapshotError,
        capture_snapshot,
        recover_snapshot,
        restore_snapshot,
    )

    workspaces_root = tmp_path / "workspaces"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(workspaces_root))
    _patch_fake_btrfs(monkeypatch)
    project = _create_project_repo(workspaces_root)
    tracked = project / "tracked.txt"

    monkeypatch.chdir(project)
    snapshot = capture_snapshot("project-before", project_id="summitflow")

    tracked.write_text("project-after\n", encoding="utf-8")
    recovered = recover_snapshot(snapshot.id, project_id="summitflow", name="project-inspection")
    recovery_path = Path(recovered.recovery_path or "")

    assert recovered.scope_type == "project"
    assert recovery_path == workspaces_root / "projects" / "project-inspection"
    assert tracked.read_text(encoding="utf-8") == "project-after\n"
    assert (recovery_path / "tracked.txt").read_text(encoding="utf-8") == "one\n"

    with pytest.raises(
        SnapshotError,
        match="Destructive rollback is only allowed for task lanes",
    ):
        restore_snapshot(snapshot.id, project_id="summitflow")


def test_project_snapshot_restore_replaces_git_state_in_place(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.quick_snapshots import capture_snapshot, restore_project_snapshot

    workspaces_root = tmp_path / "workspaces"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(workspaces_root))
    _patch_fake_btrfs(monkeypatch)
    project = _create_project_repo(workspaces_root)
    tracked = project / "tracked.txt"

    monkeypatch.chdir(project)
    snapshot = capture_snapshot("project-baseline", project_id="summitflow")
    baseline_head = _git(project, "rev-parse", "HEAD").stdout.strip()

    tracked.write_text("two\n", encoding="utf-8")
    _git(project, "add", "tracked.txt")
    _git(project, "commit", "-m", "after snapshot")
    changed_head = _git(project, "rev-parse", "HEAD").stdout.strip()
    assert changed_head != baseline_head

    restored = restore_project_snapshot(snapshot.id, project_id="summitflow")

    assert restored.id == snapshot.id
    assert restored.scope_type == "project"
    assert tracked.read_text(encoding="utf-8") == "one\n"
    assert _git(project, "rev-parse", "HEAD").stdout.strip() == baseline_head


def test_get_snapshot_usage_parses_btrfs_du_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.quick_snapshots import QuickSnapshot, get_snapshot_usage

    snapshot_path = tmp_path / "snap"
    snapshot_path.mkdir(parents=True)

    def _fake_btrfs(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        del cwd
        assert args == ["filesystem", "du", "--raw", "-s", str(snapshot_path)]
        return subprocess.CompletedProcess(
            ["btrfs", *args],
            0,
            (
                "     Total   Exclusive  Set shared  Filename\n"
                f" 920190976           0   421191680  {snapshot_path}\n"
            ),
            "",
        )

    monkeypatch.setattr("cli.lib.quick_snapshots._btrfs", _fake_btrfs)

    snapshot = QuickSnapshot(
        id="snap-1",
        name="latest",
        project_id="summitflow",
        repo_root=str(tmp_path / "repo"),
        worktree_path=str(tmp_path / "lane"),
        scope_type="lane",
        scope_name="task-123",
        snapshot_path=str(snapshot_path),
        branch="main",
        head_oid="abc123",
        head_ref="refs/heads/main",
        git_dir=str(tmp_path / ".git"),
        index_artifact_path=None,
        created_at="2026-03-21T00:00:00+00:00",
    )

    usage = get_snapshot_usage(snapshot)

    assert usage is not None
    assert usage.total_bytes == 920190976
    assert usage.exclusive_bytes == 0
    assert usage.shared_bytes == 421191680


def test_snapshot_subcommands_accept_negative_index(monkeypatch: pytest.MonkeyPatch) -> None:
    from cli.commands.snapshots import app

    captured: dict[str, str] = {}

    fake_snapshot = type(
        "Snapshot",
        (),
        {
            "id": "snap-1",
            "name": "latest",
            "backend": "btrfs",
            "source": "manual",
            "scope_type": "lane",
            "scope_name": "task-123",
            "created_at": "2025-01-01T00:00:00+00:00",
            "branch": "main",
            "head_oid": "abc123",
            "worktree_path": "/tmp/lane",
        },
    )()

    def _fake_restore(target: str, project_id: str) -> object:
        captured["target"] = target
        captured["project_id"] = project_id
        return fake_snapshot

    def _fake_recover(target: str, project_id: str, name: str | None = None) -> object:
        captured["recover_target"] = target
        captured["recover_project_id"] = project_id
        captured["recover_name"] = name
        return type(
            "Snapshot",
            (),
            {
                "id": "snap-2",
                "name": "latest",
                "backend": "btrfs",
                "scope_type": "lane",
                "scope_name": "task-123",
                "recovery_path": "/tmp/recovered",
                "recovery_branch": "recover-task-123-inspect",
            },
        )()

    def _fake_list_snapshots(project_id: str, cwd=None) -> list[object]:
        return [fake_snapshot]

    def _fake_resolve_repo_root(cwd=None):
        return Path("/tmp/lane")

    def _fake_resolve_scope(repo_root, project_id):
        from cli.lib.quick_snapshots import SnapshotScope

        return SnapshotScope("lane", "task-123", Path("/tmp/lane"))

    monkeypatch.setenv("ST_PROJECT_ID", "summitflow")
    monkeypatch.setattr("cli.commands.snapshots.restore_snapshot", _fake_restore)
    monkeypatch.setattr("cli.commands.snapshots.recover_snapshot", _fake_recover)
    monkeypatch.setattr("cli.commands.snapshots.list_snapshots", _fake_list_snapshots)
    monkeypatch.setattr("cli.lib.quick_snapshots._resolve_repo_root", _fake_resolve_repo_root)
    monkeypatch.setattr("cli.lib.quick_snapshots.resolve_scope", _fake_resolve_scope)

    # Rollback first pass: preview (exit 0, shows confirm token)
    rollback_preview = runner.invoke(app, ["rollback", "-1"])
    assert rollback_preview.exit_code == 0, f"Preview failed: {rollback_preview.output}"
    assert "--confirm" in rollback_preview.output

    # Rollback second pass: execute with token
    import re

    token_match = re.search(r"--confirm (\w+)", rollback_preview.output)
    assert token_match, f"No confirm token in output: {rollback_preview.output}"
    token = token_match.group(1)

    rollback = runner.invoke(app, ["rollback", "-1", "--confirm", token])
    assert rollback.exit_code == 0

    # Recover still works (no two-pass needed)
    recover = runner.invoke(app, ["recover", "-1", "--name", "inspect"])
    assert recover.exit_code == 0

    assert captured["target"] == "-1"
    assert captured["project_id"] == "summitflow"
    assert captured["recover_target"] == "-1"
    assert captured["recover_name"] == "inspect"


def test_snaps_compact_includes_usage_totals(monkeypatch: pytest.MonkeyPatch) -> None:
    from cli.main import app

    snapshot = type(
        "Snapshot",
        (),
        {
            "id": "snap-1",
            "name": "latest",
            "backend": "btrfs",
            "source": "manual",
            "scope_type": "lane",
            "scope_name": "task-123",
            "created_at": "2026-03-21T00:00:00+00:00",
            "branch": "main",
            "head_oid": "abc123",
            "last_restored_at": None,
            "last_recovered_at": None,
            "to_dict": lambda self=None: {"id": "snap-1"},
        },
    )()

    usage = type(
        "Usage",
        (),
        {
            "total_bytes": 2048,
            "exclusive_bytes": 1024,
            "shared_bytes": 512,
            "to_dict": lambda self=None: {
                "total_bytes": 2048,
                "exclusive_bytes": 1024,
                "shared_bytes": 512,
            },
        },
    )()

    monkeypatch.setenv("ST_PROJECT_ID", "summitflow")
    monkeypatch.setattr("cli.commands.snapshots.list_snapshots", lambda project_id: [snapshot])
    monkeypatch.setattr("cli.commands.snapshots.get_snapshot_usage", lambda snapshot: usage)

    result = runner.invoke(app, ["snaps"])

    assert result.exit_code == 0
    assert "SNAPS[1]|total:2.0KiB|exclusive:1.0KiB|shared:512B" in result.output
    assert "SNAP 1|snap-1|" in result.output
    assert "total:2.0KiB|exclusive:1.0KiB|shared:512B" in result.output


def test_prune_compact_includes_policy_when_nothing_to_prune(monkeypatch: pytest.MonkeyPatch) -> None:
    from cli.main import app

    monkeypatch.setattr("cli.commands.snapshots.prune_all", lambda dry_run=False: {})

    result = runner.invoke(app, ["prune", "--dry-run"])

    assert result.exit_code == 0
    assert "PRUNE[0]|action:would-prune|" in result.output
    assert "lane_keep:24" in result.output
    assert "project_keep:7" in result.output
    assert "manual_keep:20" in result.output


def test_root_snapshot_commands_accept_negative_index(monkeypatch: pytest.MonkeyPatch) -> None:
    from cli.main import app

    captured: dict[str, str] = {}

    fake_snapshot = type(
        "Snapshot",
        (),
        {
            "id": "snap-1",
            "name": "latest",
            "backend": "btrfs",
            "source": "manual",
            "scope_type": "lane",
            "scope_name": "task-123",
            "created_at": "2025-01-01T00:00:00+00:00",
            "branch": "main",
            "head_oid": "abc123",
            "worktree_path": "/tmp/lane",
        },
    )()

    def _fake_restore(target: str, project_id: str) -> object:
        captured["target"] = target
        captured["project_id"] = project_id
        return fake_snapshot

    def _fake_recover(target: str, project_id: str, name: str | None = None) -> object:
        captured["recover_target"] = target
        captured["recover_project_id"] = project_id
        captured["recover_name"] = name
        return type(
            "Snapshot",
            (),
            {
                "id": "snap-2",
                "name": "latest",
                "backend": "btrfs",
                "scope_type": "lane",
                "scope_name": "task-123",
                "recovery_path": "/tmp/recovered",
                "recovery_branch": "recover-task-123-inspect",
            },
        )()

    def _fake_list_snapshots(project_id: str, cwd=None) -> list[object]:
        return [fake_snapshot]

    def _fake_resolve_repo_root(cwd=None):
        return Path("/tmp/lane")

    def _fake_resolve_scope(repo_root, project_id):
        from cli.lib.quick_snapshots import SnapshotScope

        return SnapshotScope("lane", "task-123", Path("/tmp/lane"))

    monkeypatch.setenv("ST_PROJECT_ID", "summitflow")
    monkeypatch.setattr("cli.commands.snapshots.restore_snapshot", _fake_restore)
    monkeypatch.setattr("cli.commands.snapshots.recover_snapshot", _fake_recover)
    monkeypatch.setattr("cli.commands.snapshots.list_snapshots", _fake_list_snapshots)
    monkeypatch.setattr("cli.lib.quick_snapshots._resolve_repo_root", _fake_resolve_repo_root)
    monkeypatch.setattr("cli.lib.quick_snapshots.resolve_scope", _fake_resolve_scope)

    # Rollback preview (first pass)
    rollback_preview = runner.invoke(app, ["rollback", "-1"])
    assert rollback_preview.exit_code == 0, f"Preview failed: {rollback_preview.output}"
    assert "--confirm" in rollback_preview.output

    # Rollback execute (second pass with token)
    import re

    token_match = re.search(r"--confirm (\w+)", rollback_preview.output)
    assert token_match, f"No confirm token in output: {rollback_preview.output}"
    token = token_match.group(1)

    rollback = runner.invoke(app, ["rollback", "-1", "--confirm", token])
    assert rollback.exit_code == 0

    # Recover still works
    recover = runner.invoke(app, ["recover", "-1", "--name", "inspect"])
    assert recover.exit_code == 0

    assert captured["target"] == "-1"
    assert captured["project_id"] == "summitflow"
    assert captured["recover_target"] == "-1"
    assert captured["recover_name"] == "inspect"
