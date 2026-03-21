"""Tests for Btrfs autosnapshot policy library."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


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
    (repo / "tracked.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")


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
    canonical.mkdir(parents=True, exist_ok=True)
    if not (canonical / ".git").exists():
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


def _setup_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    workspaces_root = tmp_path / "workspaces"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(workspaces_root))
    _patch_fake_btrfs(monkeypatch)
    return workspaces_root


# --- ensure_baseline ---


def test_ensure_baseline_creates_snapshot_when_none_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.autosnapshot import ensure_baseline

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    _, lane = _create_lane_repo(workspaces_root)
    monkeypatch.chdir(lane)

    result = ensure_baseline(project_id="summitflow", cwd=lane)
    assert result is not None
    assert result.source == "auto-baseline"
    assert result.name == "auto-baseline"


def test_ensure_baseline_skips_when_recent_baseline_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.autosnapshot import ensure_baseline
    from cli.lib.quick_snapshots import capture_snapshot

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    _, lane = _create_lane_repo(workspaces_root)
    monkeypatch.chdir(lane)

    # Create a recent snapshot first
    capture_snapshot("manual-snap", project_id="summitflow", cwd=lane)

    # ensure_baseline should skip since there's a recent snapshot
    result = ensure_baseline(project_id="summitflow", cwd=lane)
    assert result is None


def test_ensure_baseline_creates_when_baseline_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.autosnapshot import AutosnapshotPolicy, ensure_baseline
    from cli.lib.quick_snapshots import (
        _resolve_repo_root,
        capture_snapshot,
        load_manifest,
        resolve_scope,
        save_manifest,
    )

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    _, lane = _create_lane_repo(workspaces_root)
    monkeypatch.chdir(lane)

    # Create a snapshot and backdate it
    snap = capture_snapshot("old-snap", project_id="summitflow", cwd=lane)
    repo_root = _resolve_repo_root(lane)
    scope = resolve_scope(repo_root, "summitflow")
    entries = load_manifest("summitflow", scope)

    stale_time = (datetime.now(UTC) - timedelta(minutes=60)).isoformat()
    for entry in entries:
        if entry.id == snap.id:
            # Replace with backdated entry
            idx = entries.index(entry)
            from dataclasses import asdict

            from cli.lib.quick_snapshots import QuickSnapshot

            d = asdict(entry)
            d["created_at"] = stale_time
            entries[idx] = QuickSnapshot.from_dict(d)
    save_manifest("summitflow", scope, entries)

    policy = AutosnapshotPolicy(baseline_stale_minutes=30)
    result = ensure_baseline(project_id="summitflow", cwd=lane, policy=policy)
    assert result is not None
    assert result.source == "auto-baseline"


# --- enumerate_active_scopes ---


def test_enumerate_active_scopes_finds_lanes_and_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.autosnapshot import enumerate_active_scopes

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    _create_lane_repo(workspaces_root, lane_name="task-aaa")
    _create_project_repo(workspaces_root)

    scopes = enumerate_active_scopes()
    scope_keys = [(pid, s.scope_type, s.scope_name) for pid, s in scopes]

    assert ("summitflow", "lane", "task-aaa") in scope_keys
    assert ("summitflow", "project", "summitflow") in scope_keys


# --- sweep_periodic ---


def test_sweep_creates_periodic_for_due_lanes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.autosnapshot import sweep_periodic

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    _create_lane_repo(workspaces_root, lane_name="task-sweep")
    _create_project_repo(workspaces_root)

    # No snapshots exist yet, so everything is "due"
    created = sweep_periodic()
    assert len(created) >= 1
    sources = [s.source for s in created]
    assert all(s == "auto-periodic" for s in sources)


def test_sweep_skips_lanes_with_recent_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.autosnapshot import sweep_periodic
    from cli.lib.quick_snapshots import capture_snapshot

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    _, lane = _create_lane_repo(workspaces_root, lane_name="task-recent")
    _create_project_repo(workspaces_root)

    # Create a fresh snapshot in the lane
    monkeypatch.chdir(lane)
    capture_snapshot("fresh", project_id="summitflow", cwd=lane)

    created = sweep_periodic()
    # Lane should be skipped, but project may still get one
    lane_snaps = [s for s in created if s.scope_type == "lane" and s.scope_name == "task-recent"]
    assert len(lane_snaps) == 0


# --- prune ---


def test_prune_keeps_configured_auto_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.autosnapshot import AutosnapshotPolicy, prune_scope
    from cli.lib.quick_snapshots import (
        _resolve_repo_root,
        capture_snapshot,
        load_manifest,
        resolve_scope,
    )

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    _, lane = _create_lane_repo(workspaces_root)
    monkeypatch.chdir(lane)

    # Create 5 auto snapshots
    for i in range(5):
        capture_snapshot(f"auto-{i}", project_id="summitflow", cwd=lane, source="auto-periodic")

    repo_root = _resolve_repo_root(lane)
    scope = resolve_scope(repo_root, "summitflow")

    # Policy: keep only 3 auto
    policy = AutosnapshotPolicy(auto_keep_per_scope=3)
    pruned = prune_scope(project_id="summitflow", scope=scope, policy=policy)
    assert len(pruned) == 2  # 5 - 3 = 2 pruned

    remaining = load_manifest("summitflow", scope)
    assert len(remaining) == 3


def test_prune_deletes_btrfs_subvolumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.autosnapshot import AutosnapshotPolicy, prune_scope
    from cli.lib.quick_snapshots import (
        _resolve_repo_root,
        capture_snapshot,
        resolve_scope,
    )

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    _, lane = _create_lane_repo(workspaces_root)
    monkeypatch.chdir(lane)

    snaps = []
    for i in range(4):
        snaps.append(capture_snapshot(f"auto-{i}", project_id="summitflow", cwd=lane, source="auto-periodic"))

    # Verify snapshot paths exist before prune
    for snap in snaps:
        assert Path(snap.snapshot_path).exists()

    repo_root = _resolve_repo_root(lane)
    scope = resolve_scope(repo_root, "summitflow")

    policy = AutosnapshotPolicy(auto_keep_per_scope=2)
    pruned = prune_scope(project_id="summitflow", scope=scope, policy=policy)
    assert len(pruned) == 2

    # Pruned snapshot paths should be gone
    for entry in pruned:
        assert not Path(entry.snapshot_path).exists()

    # Kept ones should still exist
    kept_ids = {s.id for s in snaps} - {e.id for e in pruned}
    for snap in snaps:
        if snap.id in kept_ids:
            assert Path(snap.snapshot_path).exists()


def test_prune_preserves_manual_snapshots_within_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.autosnapshot import AutosnapshotPolicy, prune_scope
    from cli.lib.quick_snapshots import (
        _resolve_repo_root,
        capture_snapshot,
        load_manifest,
        resolve_scope,
    )

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    _, lane = _create_lane_repo(workspaces_root)
    monkeypatch.chdir(lane)

    # 3 manual + 4 auto snapshots
    for i in range(3):
        capture_snapshot(f"manual-{i}", project_id="summitflow", cwd=lane, source="manual")
    for i in range(4):
        capture_snapshot(f"auto-{i}", project_id="summitflow", cwd=lane, source="auto-periodic")

    repo_root = _resolve_repo_root(lane)
    scope = resolve_scope(repo_root, "summitflow")

    # Keep 2 auto, 5 manual (all manual should survive)
    policy = AutosnapshotPolicy(auto_keep_per_scope=2, manual_keep_per_scope=5)
    pruned = prune_scope(project_id="summitflow", scope=scope, policy=policy)

    # Only auto excess should be pruned (4 - 2 = 2)
    assert len(pruned) == 2
    assert all(e.source == "auto-periodic" for e in pruned)

    remaining = load_manifest("summitflow", scope)
    manual_remaining = [e for e in remaining if e.source == "manual"]
    assert len(manual_remaining) == 3  # all manual preserved


# --- source field round-trip ---


def test_source_field_round_trips_through_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.quick_snapshots import (
        capture_snapshot,
        list_snapshots,
    )

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    _, lane = _create_lane_repo(workspaces_root)
    monkeypatch.chdir(lane)

    # Create snapshots with different sources
    capture_snapshot("manual-test", project_id="summitflow", cwd=lane, source="manual")
    capture_snapshot("claim-test", project_id="summitflow", cwd=lane, source="auto-claim")
    capture_snapshot("periodic-test", project_id="summitflow", cwd=lane, source="auto-periodic")

    # Reload from manifest
    loaded = list_snapshots(project_id="summitflow", cwd=lane)
    sources_by_name = {e.name: e.source for e in loaded}

    assert sources_by_name["manual-test"] == "manual"
    assert sources_by_name["claim-test"] == "auto-claim"
    assert sources_by_name["periodic-test"] == "auto-periodic"


def test_source_field_defaults_to_manual_for_old_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Old manifests without a ``source`` field should load as ``manual``."""
    from cli.lib.quick_snapshots import QuickSnapshot

    data = {
        "id": "old-snap-123",
        "name": "legacy",
        "project_id": "summitflow",
        "repo_root": "/tmp/repo",
        "worktree_path": "/tmp/lane",
        "scope_type": "lane",
        "scope_name": "task-old",
        "snapshot_path": "/tmp/snap",
        "branch": "main",
        "head_oid": "abc123",
        "head_ref": "refs/heads/main",
        "git_dir": "/tmp/.git",
        "index_artifact_path": None,
        "created_at": "2025-01-01T00:00:00+00:00",
        "backend": "btrfs",
        # No "source" key — simulating old manifest
    }

    snap = QuickSnapshot.from_dict(data)
    assert snap.source == "manual"


def test_prune_dry_run_does_not_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.autosnapshot import AutosnapshotPolicy, prune_scope
    from cli.lib.quick_snapshots import (
        _resolve_repo_root,
        capture_snapshot,
        load_manifest,
        resolve_scope,
    )

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    _, lane = _create_lane_repo(workspaces_root)
    monkeypatch.chdir(lane)

    for i in range(5):
        capture_snapshot(f"auto-{i}", project_id="summitflow", cwd=lane, source="auto-periodic")

    repo_root = _resolve_repo_root(lane)
    scope = resolve_scope(repo_root, "summitflow")

    policy = AutosnapshotPolicy(auto_keep_per_scope=3)
    pruned = prune_scope(project_id="summitflow", scope=scope, policy=policy, dry_run=True)
    assert len(pruned) == 2

    # Nothing actually deleted
    remaining = load_manifest("summitflow", scope)
    assert len(remaining) == 5  # still all 5
    for entry in pruned:
        assert Path(entry.snapshot_path).exists()


def test_prune_all_prunes_orphaned_lane_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.autosnapshot import AutosnapshotPolicy, prune_all
    from cli.lib.quick_snapshots import capture_snapshot

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    canonical, lane = _create_lane_repo(workspaces_root, lane_name="task-orphan")
    monkeypatch.chdir(lane)

    snaps = []
    for i in range(3):
        snaps.append(capture_snapshot(f"auto-{i}", project_id="summitflow", cwd=lane, source="auto-periodic"))

    _git(canonical, "worktree", "remove", str(lane), "--force")
    assert not lane.exists()

    results = prune_all(policy=AutosnapshotPolicy(auto_keep_per_scope=1))

    assert "summitflow/lane:task-orphan" in results
    assert len(results["summitflow/lane:task-orphan"]) == 2

    pruned_ids = {entry.id for entry in results["summitflow/lane:task-orphan"]}
    for snap in snaps:
        if snap.id in pruned_ids:
            assert not Path(snap.snapshot_path).exists()
        else:
            assert Path(snap.snapshot_path).exists()
