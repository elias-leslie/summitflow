"""Saved source recovery, retention and isolated native Btrfs regression checks."""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from cli.lib import autosnapshot as auto
from cli.lib import leases
from cli.lib import quick_snapshots as snap
from cli.lib.snapshots import _saved_work as saved
from cli.lib.snapshots._manifest import _manifest_path
from cli.lib.snapshots._models import QuickSnapshot, SnapshotError


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "snapshot@test.invalid")
    git(root, "config", "user.name", "Snapshot test")
    (root / "source.txt").write_text("committed\n")
    (root / ".gitignore").write_text("ignored.txt\nnode_modules/\n")
    git(root, "add", ".")
    git(root, "commit", "--allow-empty", "-m", "fixture")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(leases, "LEASES_DIR", home / "leases")
    monkeypatch.setenv("ST_SESSION_ID", "saved-work-test")
    root = tmp_path / "workspace"
    project = root / "projects" / "fixture"
    init_repo(project)
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(root))
    monkeypatch.setattr(snap, "_require_btrfs_subvolume", lambda _: None)
    monkeypatch.setattr(snap, "_require_readonly_point", lambda _: None)
    monkeypatch.setattr(snap, "_capture_boundary", lambda _: root)
    monkeypatch.setattr(snap.shutil, "disk_usage", lambda _: SimpleNamespace(free=100 * 1024 ** 3))
    calls = []
    def snapshot(source, destination, *, readonly):
        calls.append((source, destination, readonly))
        shutil.copytree(source, destination, symlinks=True, ignore=shutil.ignore_patterns(".snapshots"))
    monkeypatch.setattr(snap, "_snapshot_subvolume", snapshot)
    monkeypatch.setattr(snap, "_delete_subvolume", lambda p: shutil.rmtree(p) if p.exists() else None)
    monkeypatch.setattr(auto, "delete_subvolume", lambda p: shutil.rmtree(p) if p.exists() else None)
    return SimpleNamespace(root=root, project=project, calls=calls)


def recovery_path(snapshot: QuickSnapshot) -> Path:
    assert snapshot.recovery_path is not None
    return Path(snapshot.recovery_path)


def capture(workspace, source="auto-periodic"):
    return snap.capture_snapshot("point", project_id="fixture", cwd=workspace.project, source=source)


def test_capture_shared_boundary_binds_tracked_and_untracked_metadata(workspace):
    project = workspace.project
    (project / "source.txt").write_text("saved tracked\n")
    (project / "new.txt").write_text("saved untracked\n")
    point = capture(workspace)
    tree = snap.snapshot_project_tree(point)
    assert point.capture_root == str(workspace.root)
    assert point.project_relative_path == "projects/fixture"
    assert (tree / "source.txt").read_text() == "saved tracked\n"
    assert (tree / "new.txt").read_text() == "saved untracked\n"
    assert point.head_oid == git(tree, "rev-parse", "HEAD")
    assert point.index_artifact_path is not None
    assert Path(point.index_artifact_path).read_bytes() == (tree / ".git/index").read_bytes()
    assert point.unfinished


def test_metadata_does_not_read_live_head_after_capture(workspace, monkeypatch):
    original = snap._snapshot_subvolume
    old_head = git(workspace.project, "rev-parse", "HEAD")
    monkeypatch.setenv("GIT_DIR", str(workspace.project / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(workspace.project))
    def racing_capture(source, destination, *, readonly):
        original(source, destination, readonly=readonly)
        (workspace.project / "source.txt").write_text("later commit")
        git(workspace.project, "add", ".")
        git(workspace.project, "commit", "-m", "later")
        git(workspace.project, "switch", "-c", "later-branch")
    monkeypatch.setattr(snap, "_snapshot_subvolume", racing_capture)
    point = capture(workspace)
    assert point.head_oid == old_head
    assert point.branch == "main"
    assert point.head_ref == "refs/heads/main"
    assert point.source_digest != saved.source_digest(workspace.project)


def test_saved_digest_preserves_ignored_data_and_tracked_output_fixtures(workspace):
    project = workspace.project
    (project / "data").mkdir()
    (project / "data/fixture.txt").write_text("data fixture")
    (project / "node_modules").mkdir()
    (project / "node_modules/tracked-fixture.txt").write_text("fixture")
    git(project, "add", "-f", "node_modules/tracked-fixture.txt")
    baseline = saved.source_digest(project)
    (project / "ignored.txt").write_text("saved ignored source")
    assert saved.source_digest(project) != baseline
    baseline = saved.source_digest(project)
    (project / "node_modules/generated.txt").write_text("disposable")
    (project / ".dev-tools").mkdir()
    (project / ".dev-tools/acceptance.txt").write_text("disposable gate receipt")
    assert saved.source_digest(project) == baseline
    (project / "node_modules/tracked-fixture.txt").write_text("changed fixture")
    assert saved.source_digest(project) != baseline
    baseline = saved.source_digest(project)
    (project / "data/fixture.txt").write_text("changed data fixture")
    assert saved.source_digest(project) != baseline


def test_explicit_durable_classification_changes_do_not_trigger_source_point(workspace):
    project = workspace.project
    (project / "project.identity.json").write_text(json.dumps({"storage": {"durable_data": ["app-state"], "disposable_outputs": ["generated"]}}))
    for directory in ("app-state", "generated"):
        (project / directory).mkdir()
        (project / directory / "state.txt").write_text("before")
    before = saved.source_digest(project)
    (project / "app-state/state.txt").write_text("after")
    (project / "generated/state.txt").write_text("after")
    assert saved.source_digest(project) == before


@pytest.mark.parametrize("lock", ["index.lock", "HEAD.lock", "refs/heads/main.lock"])
def test_git_transaction_defers_without_creating_point(workspace, lock):
    lock_path = workspace.project / ".git" / lock
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("busy")
    with pytest.raises(SnapshotError, match="transaction"):
        capture(workspace)
    assert not workspace.calls
    lock_path.unlink()
    assert capture(workspace)


def test_long_acceptance_lock_does_not_freeze_saved_protection(workspace):
    lock = workspace.project / ".git/st/repo-mutation.lock"
    lock.parent.mkdir(parents=True)
    with lock.open("w") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        assert capture(workspace)


def test_dirty_unchanged_sweep_skips_but_runs_cleanup(workspace, monkeypatch):
    (workspace.project / "source.txt").write_text("unchanged dirty")
    point = capture(workspace)
    point.created_at = (datetime.now(UTC) - timedelta(minutes=20)).isoformat()
    scope = snap.resolve_scope(workspace.project, "fixture")
    snap.save_manifest("fixture", scope, [point])
    cleanup = []
    monkeypatch.setattr(auto, "prune_scope", lambda **kwargs: cleanup.append(kwargs) or [])
    assert auto.sweep_periodic() == []
    assert len(workspace.calls) == 1
    assert cleanup
    assert auto.LAST_SWEEP_REPORT[0]["reason"] == "saved source unchanged"
    (workspace.project / "new.txt").write_text("new saved")
    assert len(auto.sweep_periodic()) == 1


def test_pressure_skip_is_truthful_and_cleanup_continues(workspace, monkeypatch):
    monkeypatch.setattr(snap.shutil, "disk_usage", lambda _: SimpleNamespace(free=1024))
    cleanup = []
    monkeypatch.setattr(auto, "prune_scope", lambda **kwargs: cleanup.append(kwargs) or [])
    assert auto.sweep_periodic() == []
    assert "free space" in auto.LAST_SWEEP_REPORT[0]["reason"]
    assert cleanup
    assert not workspace.calls


def test_recovery_returns_readonly_project_subtree_and_pin_lifecycle(workspace):
    point = capture(workspace)
    recovered = snap.recover_snapshot(point.id, project_id="fixture", cwd=workspace.project)
    assert workspace.calls[-1][2] is True
    assert recovery_path(recovered).name == "fixture"
    assert (recovery_path(recovered) / "source.txt").read_text() == "committed\n"
    assert recovered.recovery_active and recovered.pin_reason == "active recovery"
    released = snap.release_recovery(point.id, project_id="fixture", cwd=workspace.project)
    assert not released.recovery_active and released.pin_reason is None


def test_shared_workspace_wholesale_rollback_refused(workspace):
    point = capture(workspace)
    with pytest.raises(SnapshotError, match="rollback is refused"):
        snap.restore_snapshot(point.id, project_id="fixture", cwd=workspace.project)
    assert (workspace.project / "source.txt").read_text() == "committed\n"


def own(workspace, monkeypatch, paths=None):
    monkeypatch.setattr(saved, "active_claim_paths", lambda *args: paths or ["source.txt", "new.txt"])
    leases.acquire("fixture", [str(workspace.project / "source.txt"), str(workspace.project / "new.txt")], task_id="task-fixture")


def test_selected_apply_uses_lease_claim_and_preview_current_digest(workspace, monkeypatch):
    (workspace.project / "new.txt").write_text("saved untracked")
    point = capture(workspace)
    own(workspace, monkeypatch)
    (workspace.project / "source.txt").write_text("current edit")
    (workspace.project / "new.txt").unlink()
    preview = snap.recovery_preview(point.id, project_id="fixture", cwd=workspace.project, paths=["source.txt", "new.txt"], owned_paths=["source.txt", "new.txt"])
    result = snap.apply_recovery(point.id, project_id="fixture", cwd=workspace.project, paths=["source.txt", "new.txt"], owned_paths=["source.txt", "new.txt"], preview_digest=preview["preview_digest"])
    assert result == {"ok": True, "applied": ["new.txt", "source.txt"]}
    assert (workspace.project / "new.txt").read_text() == "saved untracked"
    assert (workspace.project / "source.txt").read_text() == "committed\n"


def test_apply_rejects_intervening_edits(workspace, monkeypatch):
    point = capture(workspace)
    own(workspace, monkeypatch)
    preview = snap.recovery_preview(point.id, project_id="fixture", cwd=workspace.project, paths=["source.txt"], owned_paths=["source.txt"])
    (workspace.project / "source.txt").write_text("new edit after preview")
    with pytest.raises(SnapshotError, match="Intervening"):
        snap.apply_recovery(point.id, project_id="fixture", cwd=workspace.project, paths=["source.txt"], owned_paths=["source.txt"], preview_digest=preview["preview_digest"])
    assert (workspace.project / "source.txt").read_text() == "new edit after preview"


def test_foreign_ownership_and_unleased_paths_refused(workspace, monkeypatch):
    point = capture(workspace)
    with pytest.raises(SnapshotError, match="active own lease"):
        snap.recovery_preview(point.id, project_id="fixture", cwd=workspace.project, paths=["source.txt"], owned_paths=["source.txt"])
    own(workspace, monkeypatch)
    monkeypatch.setenv("ST_SESSION_ID", "foreign-native-session")
    leases.acquire("fixture", [str(workspace.project / "source.txt")], task_id="task-other")
    monkeypatch.setenv("ST_SESSION_ID", "saved-work-test")
    with pytest.raises(SnapshotError, match="Foreign ownership"):
        snap.recovery_preview(point.id, project_id="fixture", cwd=workspace.project, paths=["source.txt"], owned_paths=["source.txt"])


def test_declared_task_scope_cannot_be_expanded_by_caller(workspace, monkeypatch):
    point = capture(workspace)
    own(workspace, monkeypatch, paths=["different-file.py"])
    with pytest.raises(SnapshotError, match="active task's declared scope"):
        snap.recovery_preview(point.id, project_id="fixture", cwd=workspace.project, paths=["source.txt"], owned_paths=["source.txt"])


@pytest.mark.parametrize("path", [".git/HEAD", "../foreign.txt", "/absolute.txt"])
def test_selected_recovery_rejects_git_and_escape_paths(workspace, path):
    point = capture(workspace)
    with pytest.raises(SnapshotError, match="Unsafe"):
        snap.recovery_preview(point.id, project_id="fixture", cwd=workspace.project, paths=[path], owned_paths=[], verify_ownership=False)


def test_selected_recovery_rejects_classified_durable_data_and_symlink_parent(workspace):
    project = workspace.project
    (project / "project.identity.json").write_text(json.dumps({"storage": {"durable_data": ["state"]}}))
    (project / "state").mkdir()
    (project / "state/db.txt").write_text("durable state")
    (project / "link").symlink_to(project / "state", target_is_directory=True)
    point = capture(workspace)
    for path, error in [("state/db.txt", "Durable data"), ("link/db.txt", "Symlink parent")]:
        with pytest.raises(SnapshotError, match=error):
            snap.recovery_preview(point.id, project_id="fixture", cwd=project, paths=[path], owned_paths=[], verify_ownership=False)


def point_at(workspace, identity, age, **kwargs):
    point = QuickSnapshot.from_dict(capture(workspace, source="manual").to_dict())
    point.source = "auto-periodic"
    point.id = identity
    point.created_at = (datetime.now(UTC) - age).isoformat()
    for key, value in kwargs.items():
        setattr(point, key, value)
    return point


def test_time_retention_hourly_and_protected_points(workspace):
    entries = [point_at(workspace, "newest", timedelta(minutes=1))]
    entries += [point_at(workspace, f"recent-{i}", timedelta(hours=2, minutes=i)) for i in range(3)]
    # Same hour two days ago: newest hour point survives, older one is prunable.
    entries += [point_at(workspace, "hour-first", timedelta(days=2, minutes=1)), point_at(workspace, "hour-second", timedelta(days=2, minutes=2))]
    entries += [point_at(workspace, "old", timedelta(days=10)), point_at(workspace, "unfinished", timedelta(days=11), unfinished=True), point_at(workspace, "recovery", timedelta(days=12), recovery_active=True), point_at(workspace, "pinned", timedelta(days=13), pin_reason="review", pin_until=(datetime.now(UTC) + timedelta(days=1)).isoformat())]
    assert {p.id for p in auto._retention_candidates(entries, auto.DEFAULT_POLICY)} == {"hour-second", "old"}


def test_deletion_failure_retains_manifest_error_and_retry(workspace, monkeypatch):
    newest = point_at(workspace, "newest", timedelta(minutes=1))
    old = point_at(workspace, "old", timedelta(days=10))
    scope = snap.resolve_scope(workspace.project, "fixture")
    snap.save_manifest("fixture", scope, [newest, old])
    monkeypatch.setattr(auto, "delete_subvolume", lambda _: (_ for _ in ()).throw(SnapshotError("device busy")))
    assert auto.prune_scope(project_id="fixture", scope=scope) == []
    retained = snap.load_manifest("fixture", scope)
    assert len(retained) == 2 and next(e for e in retained if e.id == "old").deletion_error == "device busy"
    monkeypatch.setattr(auto, "delete_subvolume", lambda p: shutil.rmtree(p))
    assert [e.id for e in auto.prune_scope(project_id="fixture", scope=scope)] == ["old"]
    assert [e.id for e in snap.load_manifest("fixture", scope)] == ["newest"]


def test_old_manifest_compatible_defaults(workspace):
    data = capture(workspace).to_dict()
    for name in ("capture_root", "project_relative_path", "source_digest", "unfinished", "pin_reason", "pin_until", "recovery_active", "deletion_error"):
        data.pop(name)
    point = QuickSnapshot.from_dict(data)
    assert point.project_relative_path == "." and point.source_digest is None
    assert point.unfinished is None
    assert not point.recovery_active


@pytest.mark.skipif(not os.environ.get("ST_SNAPSHOT_TEST_ROOT"), reason="requires explicitly assigned isolated Btrfs test subvolume")
def test_native_btrfs_shared_capture_readonly_recovery_and_isolated_restore(tmp_path, monkeypatch):
    root = Path(os.environ["ST_SNAPSHOT_TEST_ROOT"]).resolve()
    assert root.parent == Path("/run/sf-recovery-source") and root.name.startswith("snapshot-tests-")
    assert root.exists()
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(root))
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "1")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    project = root / "projects/fixture"
    init_repo(project)
    (project / "new.txt").write_text("saved native untracked\n")
    other = root / "projects/other-native"
    init_repo(other)
    point = snap.capture_snapshot("native", project_id="fixture", cwd=project, source="auto-periodic")
    shared = snap.capture_snapshot("native", project_id="other-native", cwd=other, source="auto-periodic")
    assert shared.shared_capture and shared.snapshot_path == point.snapshot_path
    assert point.capture_root == str(root)
    assert (snap.snapshot_project_tree(point) / "new.txt").read_text() == "saved native untracked\n"
    recovered = snap.recover_snapshot(point.id, project_id="fixture", cwd=project)
    native_ro = subprocess.run(["btrfs", "property", "get", str(recovery_path(recovered).parents[1]), "ro"], check=True, capture_output=True, text=True)
    assert "ro=true" in native_ro.stdout
    with pytest.raises(OSError):
        (recovery_path(recovered) / "new.txt").write_text("forbidden")
    with pytest.raises(SnapshotError, match="rollback is refused"):
        snap.restore_snapshot(point.id, project_id="fixture", cwd=project)
    # Whole-project legacy restore remains available only for isolated native projects.
    isolated = root / "projects/isolated"
    subprocess.run(["btrfs", "subvolume", "create", str(isolated)], check=True, capture_output=True)
    init_repo(isolated)
    isolated_point = snap.capture_snapshot("isolated", project_id="isolated", cwd=isolated)
    (isolated / "source.txt").write_text("later saved edit")
    # This mount does not permit unprivileged subvolume deletion; use its authorized
    # isolated test cleanup privilege solely for the controlled restore fixture.
    original = snap._btrfs
    def btrfs(args, *, cwd=None):
        if args[:2] == ["subvolume", "delete"]:
            assert str(args[-1]).startswith(str(root) + "/")
            return subprocess.run(["sudo", "-n", "btrfs", *args], check=True, capture_output=True, text=True)
        return original(args, cwd=cwd)
    monkeypatch.setattr(snap, "_btrfs", btrfs)
    snap.restore_snapshot(isolated_point.id, project_id="isolated", cwd=isolated)
    assert (isolated / "source.txt").read_text() == "committed\n"


def test_apply_file_rejects_a_swapped_symlink_parent(tmp_path):
    root = tmp_path / "project"
    outside = tmp_path / "foreign"
    root.mkdir()
    outside.mkdir()
    (outside / "source.txt").write_text("foreign data")
    (root / "parent").symlink_to(outside, target_is_directory=True)
    source = tmp_path / "captured.txt"
    source.write_text("captured")
    with pytest.raises(OSError):
        saved.apply_file(root, "parent/source.txt", source, saved.file_digest(outside / "source.txt"))
    assert (outside / "source.txt").read_text() == "foreign data"


def test_failed_duplicate_capture_cleanup_retains_physical_manifest(workspace, monkeypatch):
    point = capture(workspace)
    point.created_at = (datetime.now(UTC) - timedelta(minutes=16)).isoformat()
    snap.save_manifest("fixture", snap.resolve_scope(workspace.project, "fixture"), [point])
    monkeypatch.setattr(snap, "_delete_subvolume", lambda _: (_ for _ in ()).throw(SnapshotError("permission denied")))
    with pytest.raises(SnapshotError, match="cleanup failed"):
        capture(workspace)
    scope = snap.resolve_scope(workspace.project, "fixture")
    points = snap.load_manifest("fixture", scope)
    assert len(points) == 2
    failed = next(point for point in points if point.deletion_error)
    assert Path(failed.snapshot_path).exists()
    assert failed.deletion_error is not None
    assert "permission denied" in failed.deletion_error


@pytest.mark.parametrize("change", ["foreign", "expired", "completed", "unregistered"])
def test_active_claim_owner_proof_fails_closed(workspace, monkeypatch, change):
    task = {"status": "running", "claimed_by": "canonical-owner", "lock_expires_at": datetime.now(UTC) + timedelta(minutes=30)}
    monkeypatch.setattr("cli.lib.task_claims._renewal_config", lambda root: (SimpleNamespace(project_id="fixture"), True))
    monkeypatch.setattr("cli.lib.task_claims.current_worker_id", lambda: "canonical-owner")
    monkeypatch.setattr("app.storage.tasks.get_task", lambda _: task)
    monkeypatch.setattr("app.storage.projects.get_project_root_path", lambda _: str(workspace.project) if change != "unregistered" else None)
    monkeypatch.setattr("app.storage.task_spirit.get_task_spirit", lambda _: {"context": {"files_to_modify": ["source.txt"]}})
    if change == "foreign":
        task["claimed_by"] = "another-owner"
    elif change == "expired":
        task["lock_expires_at"] = datetime.now(UTC) - timedelta(minutes=1)
    elif change == "completed":
        task["status"] = "completed"
    with pytest.raises(SnapshotError, match="canonical task"):
        saved.active_claim_paths("fixture", workspace.project, "task-fixture")


def test_recovery_release_preserves_an_independent_review_pin(workspace):
    point = capture(workspace)
    point.pin_reason = "independent review"
    point.pin_until = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    scope = snap.resolve_scope(workspace.project, "fixture")
    snap.save_manifest("fixture", scope, [point])
    recovered = snap.recover_snapshot(point.id, project_id="fixture", cwd=workspace.project)
    assert recovered.pin_reason == "independent review"
    released = snap.release_recovery(point.id, project_id="fixture", cwd=workspace.project)
    assert not released.recovery_active
    assert released.pin_reason == "independent review" and released.pin_until == point.pin_until


def test_capture_reuses_host_reserve_and_does_not_make_a_point(workspace, monkeypatch):
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "25")
    monkeypatch.setattr(snap.shutil, "disk_usage", lambda _: SimpleNamespace(free=21 * 1024 ** 3))
    with pytest.raises(SnapshotError, match=r"21\.00 GiB below host reserve 25\.00 GiB"):
        capture(workspace)
    assert not workspace.calls


def test_projects_share_one_physical_point_and_prune_keeps_other_view(workspace):
    other = workspace.root / "projects/other"
    init_repo(other)
    first = capture(workspace)
    second = snap.capture_snapshot("point", project_id="other", cwd=other, source="auto-periodic")
    assert first.snapshot_path == second.snapshot_path and second.shared_capture
    assert len(workspace.calls) == 1
    # Drop one project view without deleting the shared physical point.
    scope = snap.resolve_scope(workspace.project, "fixture")
    entries = snap.load_manifest("fixture", scope)
    entries[0].source = "manual"
    snap.save_manifest("fixture", scope, entries)
    assert [p.id for p in auto.prune_scope(project_id="fixture", scope=scope, policy=auto.AutosnapshotPolicy(manual_keep_per_scope=0))] == [first.id]
    assert Path(second.snapshot_path).exists()
    assert snap.list_snapshots(project_id="other", cwd=other)


def test_same_boundary_new_edits_are_deferred_instead_of_multiplied(workspace):
    other = workspace.root / "projects/other"
    init_repo(other)
    capture(workspace)
    (other / "new.txt").write_text("saved after physical point")
    with pytest.raises(SnapshotError, match="one physical point per boundary/15 minutes"):
        snap.capture_snapshot("point", project_id="other", cwd=other, source="auto-periodic")
    assert len(workspace.calls) == 1
    assert not snap.list_snapshots(project_id="other", cwd=other)


def test_repeated_recovery_cannot_override_catalogued_copy(workspace):
    point = capture(workspace)
    first = snap.recover_snapshot(point.id, project_id="fixture", cwd=workspace.project, name="first")
    with pytest.raises(SnapshotError, match="already catalogued"):
        snap.recover_snapshot(point.id, project_id="fixture", cwd=workspace.project, name="second")
    assert recovery_path(first).exists()
    released = snap.release_recovery(point.id, project_id="fixture", cwd=workspace.project)
    assert not released.recovery_active
    assert len(released.recovery_copies) == 1
    with pytest.raises(SnapshotError, match="release and prune"):
        snap.recover_snapshot(point.id, project_id="fixture", cwd=workspace.project, name="second")
    scope = snap.resolve_scope(workspace.project, "fixture")
    auto.prune_scope(project_id="fixture", scope=scope)
    assert not recovery_path(first).exists()
    second = snap.recover_snapshot(point.id, project_id="fixture", cwd=workspace.project, name="second")
    assert len(second.recovery_copies) == 2
    assert second.recovery_copies[0]["deleted_at"]


def test_released_recovery_deletion_failure_is_catalogued_and_retried(workspace, monkeypatch):
    point = capture(workspace)
    recovered = snap.recover_snapshot(point.id, project_id="fixture", cwd=workspace.project)
    snap.release_recovery(point.id, project_id="fixture", cwd=workspace.project)
    scope = snap.resolve_scope(workspace.project, "fixture")
    monkeypatch.setattr(auto, "delete_subvolume", lambda _: (_ for _ in ()).throw(SnapshotError("clone busy")))
    assert auto.prune_scope(project_id="fixture", scope=scope) == []
    retained = snap.load_manifest("fixture", scope)[0]
    assert retained.recovery_copies[0]["deletion_error"] == "clone busy"
    assert recovery_path(recovered).exists()
    monkeypatch.setattr(auto, "delete_subvolume", lambda p: shutil.rmtree(p))
    auto.prune_scope(project_id="fixture", scope=scope)
    cleaned = snap.load_manifest("fixture", scope)[0]
    assert cleaned.recovery_copies[0]["deleted_at"] and cleaned.recovery_copies[0]["deletion_error"] is None
    assert not recovery_path(recovered).exists()


def test_unreleased_copy_stays_protected_and_prune_preview_preserves_it(workspace):
    point = capture(workspace)
    recovered = snap.recover_snapshot(point.id, project_id="fixture", cwd=workspace.project)
    scope = snap.resolve_scope(workspace.project, "fixture")
    assert auto.prune_scope(project_id="fixture", scope=scope, dry_run=True) == []
    assert auto.prune_scope(project_id="fixture", scope=scope) == []
    assert recovery_path(recovered).exists()
    assert snap.load_manifest("fixture", scope)[0].recovery_active


@pytest.mark.skipif(not os.environ.get("ST_SNAPSHOT_TEST_ROOT"), reason="requires explicitly assigned isolated Btrfs source")
def test_native_nested_saved_source_is_refused_and_disposable_tracked_fixture_preserved(tmp_path, monkeypatch):
    root = Path(os.environ["ST_SNAPSHOT_TEST_ROOT"]).resolve()
    assert root.parent == Path("/run/sf-recovery-source") and root.name.startswith("snapshot-tests-")
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(root))
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "1")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    project = root / "projects/nested-fixture"
    init_repo(project)
    nested = project / "modules"
    subprocess.run(["btrfs", "subvolume", "create", str(nested)], check=True, capture_output=True)
    (nested / "saved.txt").write_text("saved nested source\n")
    with pytest.raises(SnapshotError, match="saved source nested Btrfs subvolume"):
        snap.capture_snapshot("nested", project_id="nested-fixture", cwd=project)
    assert not snap.list_snapshots(project_id="nested-fixture", cwd=project)
    (project / "project.identity.json").write_text(json.dumps({"storage": {"disposable_outputs": ["modules"]}}))
    git(project, "add", "modules/saved.txt")
    with pytest.raises(SnapshotError, match="saved source nested Btrfs subvolume"):
        snap.capture_snapshot("nested-tracked", project_id="nested-fixture", cwd=project)
    git(project, "rm", "--cached", "modules/saved.txt")
    (project / "project.identity.json").write_text(json.dumps({"storage": {"durable_data": ["modules"]}}))
    point = snap.capture_snapshot("declared-data", project_id="nested-fixture", cwd=project)
    assert "projects/nested-fixture/modules" in point.nested_subvolumes
    assert not (snap.snapshot_project_tree(point) / "modules/saved.txt").exists()
    assert saved.source_digest(project) == point.source_digest
    assert (nested / "saved.txt").read_text() == "saved nested source\n"


def test_released_copy_prune_preview_reports_root_without_deleting(workspace):
    point = capture(workspace)
    recovered = snap.recover_snapshot(point.id, project_id="fixture", cwd=workspace.project)
    snap.release_recovery(point.id, project_id="fixture", cwd=workspace.project)
    auto.LAST_PRUNE_REPORT.clear()
    auto.prune_scope(project_id="fixture", scope=snap.resolve_scope(workspace.project, "fixture"), dry_run=True)
    assert auto.LAST_PRUNE_REPORT[-1]["action"] == "would-delete"
    assert auto.LAST_PRUNE_REPORT[-1]["root_path"] == recovered.recovery_copies[-1]["root_path"]
    assert recovery_path(recovered).exists()


def test_reused_existing_view_keeps_active_copy_catalogue(workspace):
    point = capture(workspace)
    recovered = snap.recover_snapshot(point.id, project_id="fixture", cwd=workspace.project)
    with pytest.raises(SnapshotError, match="existing view and recovery catalogue retained"):
        capture(workspace)
    retained = snap.list_snapshots(project_id="fixture", cwd=workspace.project)[0]
    assert retained.recovery_active and retained.recovery_copies == recovered.recovery_copies
    assert retained.recovery_path == recovered.recovery_path
    assert recovery_path(retained).exists()


def test_inventory_inspects_disposable_ancestor_of_tracked_nested_fixture(workspace, monkeypatch):
    from cli.lib.snapshots import _physical
    project = workspace.project
    nested = project / "node_modules/nested-fixture"
    nested.mkdir(parents=True)
    (nested / "saved.txt").write_text("tracked fixture")
    git(project, "add", "-f", "node_modules/nested-fixture/saved.txt")
    original = Path.stat
    def nested_stat(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path == nested:
            return SimpleNamespace(st_ino=256, st_dev=result.st_dev, st_mode=result.st_mode)
        return result
    monkeypatch.setattr(Path, "stat", nested_stat)
    boundaries = _physical.inventory_nested(workspace.root, project=project)
    assert "projects/fixture/node_modules/nested-fixture" in boundaries
    with pytest.raises(SnapshotError, match="saved source nested Btrfs subvolume"):
        _physical.require_complete_project(workspace.root, project, boundaries)


@pytest.mark.parametrize("boundary_path,private_path,project_path,opaque", [
    ("/srv/workspaces", "/srv/workspaces/.btrbk", "/srv/workspaces/projects/fixture", True),
    ("/srv/workspaces", "/srv/workspaces/.btrbk", "/srv/workspaces/.btrbk/fixture", False),
    ("/srv/workspaces", "/srv/workspaces/.btrbk", "/srv/workspaces/.btrbk", False),
    ("/srv/workspaces", "/srv/workspaces/.btrbk", "/srv/workspaces", False),
    ("/srv/workspaces", "/srv/workspaces/projects/fixture/.btrbk", "/srv/workspaces/projects/fixture", False),
    ("/other/workspaces", "/other/workspaces/.btrbk", "/other/workspaces/projects/fixture", False),
    ("/srv/workspaces", "/srv/workspaces/private-sibling", "/srv/workspaces/projects/fixture", False),
    ("/srv/workspaces", "/srv/workspaces/.btrbk", None, False),
])
def test_inventory_keeps_only_canonical_private_backup_sibling_opaque(monkeypatch, boundary_path, private_path, project_path, opaque):
    from cli.lib.snapshots import _physical

    boundary, private = Path(boundary_path), Path(private_path)
    project = Path(project_path) if project_path is not None else None
    original_stat = Path.stat
    def metadata(path, *args, **kwargs):
        if path == boundary or boundary in path.parents:
            return SimpleNamespace(st_ino=100, st_dev=1, st_mode=0o040700)
        return original_stat(path, *args, **kwargs)
    monkeypatch.setattr(Path, "stat", metadata)
    monkeypatch.setattr(_physical, "_git", lambda *_: SimpleNamespace(stdout=""))
    def walk(_boundary, *, followlinks, onerror):
        assert _boundary == boundary and followlinks is False
        directories = [private.name]
        yield str(private.parent), directories, []
        if private.name in directories:
            onerror(PermissionError(13, "Permission denied", str(private)))
    monkeypatch.setattr(_physical.os, "walk", walk)

    if opaque:
        assert _physical.inventory_nested(boundary, project=project) == []
    else:
        with pytest.raises(SnapshotError, match="Cannot inventory Btrfs boundaries"):
            _physical.inventory_nested(boundary, project=project)


def test_interrupted_capture_keeps_reserved_physical_point_bounded(workspace, monkeypatch):
    original = snap._snapshot_subvolume
    def interrupted(source, destination, *, readonly):
        original(source, destination, readonly=readonly)
        raise KeyboardInterrupt("simulated process interruption")
    monkeypatch.setattr(snap, "_snapshot_subvolume", interrupted)
    with pytest.raises(KeyboardInterrupt):
        capture(workspace)
    reserved = snap.list_snapshots(project_id="fixture", cwd=workspace.project)[0]
    assert Path(reserved.snapshot_path).exists() and reserved.source_digest is None
    assert reserved.deletion_error == "Capture metadata pending"
    with pytest.raises(SnapshotError, match="incomplete"):
        capture(workspace)
    assert len(workspace.calls) == 1


@pytest.mark.parametrize("legacy_state", [{}, {"unfinished": None}])
def test_legacy_unknown_wip_remains_protected_after_retention_window(workspace, caplog, legacy_state):
    newest = point_at(workspace, "known-clean", timedelta(minutes=1), unfinished=False)
    older = point_at(workspace, "legacy-older", timedelta(days=12)).to_dict()
    unknown = point_at(workspace, "legacy-newer", timedelta(days=11)).to_dict()
    for entry in (older, unknown):
        entry.pop("unfinished")
        entry.update(legacy_state)
    scope = snap.resolve_scope(workspace.project, "fixture")
    manifest = _manifest_path("fixture", scope)
    manifest.write_text(json.dumps([newest.to_dict(), older, unknown]))
    assert auto.prune_scope(project_id="fixture", scope=scope) == []
    retained = snap.load_manifest("fixture", scope)
    assert {point.id for point in retained} == {"known-clean", "legacy-older", "legacy-newer"}
    assert all(point.unfinished is None for point in retained if point.id.startswith("legacy-"))
    # Unknown state survives rewrites without manufacturing a user retention pin.
    assert all(point.pin_reason is None for point in retained if point.id.startswith("legacy-"))
    assert "saved-work state unknown" in caplog.text
    # Explicit inspection/classification is required before retention can apply.
    for point in retained:
        if point.id.startswith("legacy-"):
            point.unfinished = False
    snap.save_manifest("fixture", scope, retained)
    assert {point.id for point in auto.prune_scope(project_id="fixture", scope=scope)} == {"legacy-older", "legacy-newer"}


@pytest.mark.parametrize("recovery_state", [{}, {"recovery_active": None}])
def test_legacy_recovery_unknown_state_preserves_unique_edits_until_release(workspace, recovery_state):
    old = point_at(workspace, "legacy-recovered", timedelta(days=12), unfinished=False)
    newest = point_at(workspace, "newest", timedelta(minutes=1), unfinished=False)
    legacy_copy = workspace.root / "projects/recover-legacy"
    legacy_copy.mkdir()
    unique = legacy_copy / "unique.txt"
    unique.write_text("unique saved recovery edit")
    raw = old.to_dict()
    raw["recovery_path"] = str(legacy_copy)
    raw["project_relative_path"] = "."
    raw["last_recovered_at"] = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    raw.pop("recovery_active")
    raw.update(recovery_state)
    raw.pop("recovery_copies")
    scope = snap.resolve_scope(workspace.project, "fixture")
    _manifest_path("fixture", scope).write_text(json.dumps([newest.to_dict(), raw]))
    assert auto.prune_scope(project_id="fixture", scope=scope) == []
    assert unique.read_text() == "unique saved recovery edit"
    retained = next(point for point in snap.load_manifest("fixture", scope) if point.id == old.id)
    assert retained.recovery_active
    assert retained.recovery_copies[0]["active"]
    assert retained.recovery_copies[0]["released_at"] is None
    with pytest.raises(SnapshotError, match="already catalogued"):
        snap.recover_snapshot(old.id, project_id="fixture", cwd=workspace.project)
    snap.release_recovery(old.id, project_id="fixture", cwd=workspace.project)
    assert unique.exists()
    assert [point.id for point in auto.prune_scope(project_id="fixture", scope=scope)] == [old.id]
    assert not legacy_copy.exists()


def test_recovery_catalogue_missing_active_flag_cannot_authorize_cleanup(workspace):
    raw = capture(workspace).to_dict()
    root = workspace.root / ".snapshots/recoveries/fixture/unknown-state"
    root.mkdir(parents=True)
    unique = root / "unique.txt"
    unique.write_text("unique saved copy edit")
    raw["recovery_copies"] = [{"root_path": str(root), "project_path": str(root),
        "created_at": raw["created_at"], "released_at": raw["created_at"], "deleted_at": None}]
    point = QuickSnapshot.from_dict(raw)
    assert point.recovery_copies[0]["active"]
    assert point.recovery_copies[0]["released_at"] is None
    assert snap.cleanup_recovery_copies(point, delete_fn=shutil.rmtree) == []
    assert unique.read_text() == "unique saved copy edit"
