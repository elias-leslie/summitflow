"""Tests for Btrfs autosnapshot policy library."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict
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


def _backdate_manifest_entries(
    cwd: Path,
    *,
    project_id: str,
    minutes_ago: int,
) -> None:
    from cli.lib.quick_snapshots import (
        QuickSnapshot,
        _resolve_repo_root,
        load_manifest,
        resolve_scope,
        save_manifest,
    )

    repo_root = _resolve_repo_root(cwd)
    scope = resolve_scope(repo_root, project_id)
    entries = load_manifest(project_id, scope)
    stale_time = (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()
    rewritten = []
    for entry in entries:
        data = asdict(entry)
        data["created_at"] = stale_time
        rewritten.append(QuickSnapshot.from_dict(data))
    save_manifest(project_id, scope, rewritten)


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
    from cli.lib.quick_snapshots import capture_snapshot

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    _, lane = _create_lane_repo(workspaces_root)
    monkeypatch.chdir(lane)

    # Create a snapshot and backdate it
    capture_snapshot("old-snap", project_id="summitflow", cwd=lane)
    (lane / "tracked.txt").write_text("two\n", encoding="utf-8")
    _backdate_manifest_entries(lane, project_id="summitflow", minutes_ago=60)

    policy = AutosnapshotPolicy(baseline_stale_minutes=30)
    result = ensure_baseline(project_id="summitflow", cwd=lane, policy=policy)
    assert result is not None
    assert result.source == "auto-baseline"


def test_ensure_baseline_skips_stale_clean_scope_without_head_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.autosnapshot import AutosnapshotPolicy, ensure_baseline
    from cli.lib.quick_snapshots import capture_snapshot

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    _, lane = _create_lane_repo(workspaces_root, lane_name="task-clean")
    monkeypatch.chdir(lane)

    capture_snapshot("old-snap", project_id="summitflow", cwd=lane)
    _backdate_manifest_entries(lane, project_id="summitflow", minutes_ago=60)

    policy = AutosnapshotPolicy(baseline_stale_minutes=30)
    result = ensure_baseline(project_id="summitflow", cwd=lane, policy=policy)

    assert result is None


def test_ensure_all_baselines_creates_for_due_active_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.autosnapshot import ensure_all_baselines

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    _create_lane_repo(workspaces_root, lane_name="task-baseline")
    _create_project_repo(workspaces_root)

    created = ensure_all_baselines()

    scope_keys = {(snap.scope_type, snap.scope_name) for snap in created}
    assert ("lane", "task-baseline") in scope_keys
    assert ("project", "summitflow") in scope_keys
    assert all(snap.source == "auto-baseline" for snap in created)


def test_ensure_all_baselines_skips_recent_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.autosnapshot import ensure_all_baselines
    from cli.lib.quick_snapshots import capture_snapshot

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    _, lane = _create_lane_repo(workspaces_root, lane_name="task-baseline-recent")
    project = _create_project_repo(workspaces_root)

    capture_snapshot("fresh-lane", project_id="summitflow", cwd=lane)
    capture_snapshot("fresh-project", project_id="summitflow", cwd=project)

    created = ensure_all_baselines()
    assert created == []


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


def test_sweep_skips_clean_scope_when_head_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.autosnapshot import sweep_periodic
    from cli.lib.quick_snapshots import capture_snapshot

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    _, lane = _create_lane_repo(workspaces_root, lane_name="task-same-head")
    monkeypatch.chdir(lane)

    capture_snapshot("older", project_id="summitflow", cwd=lane, source="auto-periodic")
    _backdate_manifest_entries(lane, project_id="summitflow", minutes_ago=120)

    created = sweep_periodic()

    lane_snaps = [
        s for s in created
        if s.scope_type == "lane" and s.scope_name == "task-same-head"
    ]
    assert lane_snaps == []


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


def test_prune_scope_uses_scope_specific_auto_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.autosnapshot import AutosnapshotPolicy, prune_scope
    from cli.lib.quick_snapshots import _resolve_repo_root, capture_snapshot, resolve_scope

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    _, lane = _create_lane_repo(workspaces_root, lane_name="task-retention")
    project = _create_project_repo(workspaces_root)

    for i in range(3):
        capture_snapshot(f"lane-auto-{i}", project_id="summitflow", cwd=lane, source="auto-periodic")
        capture_snapshot(f"project-auto-{i}", project_id="summitflow", cwd=project, source="auto-periodic")

    lane_scope = resolve_scope(_resolve_repo_root(lane), "summitflow")
    project_scope = resolve_scope(_resolve_repo_root(project), "summitflow")
    policy = AutosnapshotPolicy(lane_auto_keep_per_scope=2, project_auto_keep_per_scope=1)

    lane_pruned = prune_scope(project_id="summitflow", scope=lane_scope, policy=policy)
    project_pruned = prune_scope(project_id="summitflow", scope=project_scope, policy=policy)

    assert len(lane_pruned) == 1
    assert len(project_pruned) == 2


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


def test_prune_all_limits_archived_auto_lane_scope_count_per_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.autosnapshot import AutosnapshotPolicy, enumerate_snapshot_scopes, prune_all
    from cli.lib.quick_snapshots import capture_snapshot

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    canonical = None
    lane_names = [
        "task-older-1",
        "task-older-2",
        "task-keep-1",
        "task-keep-2",
        "task-keep-3",
    ]

    for lane_name in lane_names:
        maybe_canonical, lane = _create_lane_repo(workspaces_root, lane_name=lane_name)
        canonical = canonical or maybe_canonical
        monkeypatch.chdir(lane)
        capture_snapshot(
            f"{lane_name}-auto",
            project_id="summitflow",
            cwd=lane,
            source="auto-periodic",
        )
        _git(canonical, "worktree", "remove", str(lane), "--force")

    assert canonical is not None

    results = prune_all(
        policy=AutosnapshotPolicy(
            archived_lane_keep_per_project=3,
            archived_lane_auto_keep_per_scope=1,
        )
    )

    assert "summitflow/lane:task-older-1" in results
    assert "summitflow/lane:task-older-2" in results
    assert "summitflow/lane:task-keep-1" not in results
    assert "summitflow/lane:task-keep-2" not in results
    assert "summitflow/lane:task-keep-3" not in results

    remaining_archived = {
        scope.scope_name
        for project_id, scope, state in enumerate_snapshot_scopes(include_archived=True)
        if project_id == "summitflow" and state == "archived" and scope.scope_type == "lane"
    }
    assert remaining_archived == {"task-keep-1", "task-keep-2", "task-keep-3"}


def test_prune_all_preserves_manual_archived_lane_scope_outside_auto_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.autosnapshot import AutosnapshotPolicy, enumerate_snapshot_scopes, prune_all
    from cli.lib.quick_snapshots import capture_snapshot

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    canonical = None

    for lane_name in ["task-auto-1", "task-auto-2", "task-auto-3", "task-manual"]:
        maybe_canonical, lane = _create_lane_repo(workspaces_root, lane_name=lane_name)
        canonical = canonical or maybe_canonical
        monkeypatch.chdir(lane)
        source = "manual" if lane_name == "task-manual" else "auto-periodic"
        capture_snapshot(
            f"{lane_name}-snap",
            project_id="summitflow",
            cwd=lane,
            source=source,
        )
        _git(canonical, "worktree", "remove", str(lane), "--force")

    assert canonical is not None

    results = prune_all(
        policy=AutosnapshotPolicy(
            archived_lane_keep_per_project=1,
            archived_lane_auto_keep_per_scope=1,
        )
    )

    assert "summitflow/lane:task-auto-1" in results
    assert "summitflow/lane:task-auto-2" in results
    assert "summitflow/lane:task-manual" not in results

    remaining_archived = {
        scope.scope_name
        for project_id, scope, state in enumerate_snapshot_scopes(include_archived=True)
        if project_id == "summitflow" and state == "archived" and scope.scope_type == "lane"
    }
    assert remaining_archived == {"task-auto-3", "task-manual"}


def test_prune_all_uses_tighter_auto_limit_for_archived_lane_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.autosnapshot import AutosnapshotPolicy, prune_all
    from cli.lib.quick_snapshots import capture_snapshot, load_manifest, resolve_scope

    workspaces_root = _setup_env(monkeypatch, tmp_path)
    canonical, lane = _create_lane_repo(workspaces_root, lane_name="task-archived-retention")
    monkeypatch.chdir(lane)

    for i in range(4):
        capture_snapshot(
            f"archived-auto-{i}",
            project_id="summitflow",
            cwd=lane,
            source="auto-periodic",
        )

    scope = resolve_scope(lane, "summitflow")
    _git(canonical, "worktree", "remove", str(lane), "--force")

    results = prune_all(
        policy=AutosnapshotPolicy(
            lane_auto_keep_per_scope=24,
            archived_lane_auto_keep_per_scope=2,
            archived_lane_keep_per_project=3,
        )
    )

    assert len(results["summitflow/lane:task-archived-retention"]) == 2

    remaining = load_manifest("summitflow", scope)
    assert len(remaining) == 2
    assert all(entry.source == "auto-periodic" for entry in remaining)
