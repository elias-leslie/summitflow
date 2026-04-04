"""Btrfs-backed snapshot and recovery helpers for lane/project rewind.

These snapshots are designed for agentic use:
- `snap` is safe for the current Btrfs-backed scope.
- `recover` is the default restore path and creates a sibling recovery scope.
- `rollback` is destructive and intentionally limited to the current lane scope.

Lane snapshots capture the full Btrfs subvolume plus the worktree's Git index
state. The index lives outside the lane subvolume in Git's shared worktree
metadata, so Btrfs alone is not enough to recreate staged state.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
from pathlib import Path

from .snapshots._cleanup import (
    OrphanedSnapshotDir,
    SnapshotResidue,
    find_empty_lane_dirs,
    find_legacy_manifest_dirs,
    find_legacy_snapshot_roots,
    find_orphaned_lane_manifest_dirs,
    find_orphaned_snapshot_dirs,
    find_snapshot_residue,
    inspect_lane,
    list_snapshots,
)
from .snapshots._helpers import (
    _absolute_git_dir,
    _canonical_repo_root,
    _find_snapshot,
    _git,
    _head_oid,
    _head_ref,
    _now_iso,
    _parse_btrfs_du_raw,
    _require_workspaces,
    _resolve_lane_repo_root,
    _resolve_repo_root,
    _resolve_scope,
    _restore_lane_git_state,
    _safe_cwd_for_scope,
    _snapshot_id,
)
from .snapshots._manifest import (
    _copy_index_artifact,
    _load_manifest,
    _recovery_branch_name,
    _recovery_name,
    _rsync_snapshot_contents,
    _save_manifest,
    _snapshot_destination,
    _update_manifest_entries,
)
from .snapshots._models import (
    LaneInspection,
    QuickSnapshot,
    SnapshotError,
    SnapshotScope,
    SnapshotUsage,
)
from .worktree_git import WorktreeError, get_current_branch, run_git
from .worktree_helpers import force_remove_worktree
from .worktree_paths import get_lanes_base_dir, get_projects_base_dir

# ---------------------------------------------------------------------------
# Btrfs I/O primitives (kept here — tests monkeypatch these by module path)
# ---------------------------------------------------------------------------


def _btrfs(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["btrfs", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or str(exc)
        raise SnapshotError(f"Btrfs command failed: btrfs {' '.join(args)}\n{stderr}") from exc
    except OSError as exc:
        raise SnapshotError(f"Failed to run btrfs {' '.join(args)}: {exc}") from exc


def _require_btrfs_subvolume(path: Path) -> None:
    try:
        result = subprocess.run(
            ["stat", "-f", "-c", "%T", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or str(exc)
        raise SnapshotError(f"Failed to inspect filesystem type for {path}:\n{stderr}") from exc
    except OSError as exc:
        raise SnapshotError(f"Failed to inspect filesystem type for {path}: {exc}") from exc

    fs_type = result.stdout.strip()
    if fs_type != "btrfs":
        raise SnapshotError(
            f"Current scope is on '{fs_type or 'unknown'}', not btrfs.\n"
            f"  path: {path}"
        )


def _snapshot_subvolume(source: Path, destination: Path, *, readonly: bool) -> None:
    args = ["subvolume", "snapshot"]
    if readonly:
        args.append("-r")
    args.extend([str(source), str(destination)])
    _btrfs(args)


def _delete_subvolume(path: Path) -> None:
    if not path.exists():
        return
    with contextlib.suppress(SnapshotError):
        _btrfs(["property", "set", str(path), "ro", "false"])
    _btrfs(["subvolume", "delete", str(path)])


# ---------------------------------------------------------------------------
# Snapshot capture and usage
# ---------------------------------------------------------------------------


def get_snapshot_usage(snapshot: QuickSnapshot) -> SnapshotUsage | None:
    """Return Btrfs usage statistics for *snapshot*, or ``None`` if unavailable."""
    snapshot_path = Path(snapshot.snapshot_path)
    if not snapshot_path.exists():
        return None
    try:
        result = _btrfs(["filesystem", "du", "--raw", "-s", str(snapshot_path)])
        return _parse_btrfs_du_raw(result.stdout, snapshot_path)
    except SnapshotError:
        return None


def capture_snapshot(
    name: str | None,
    *,
    project_id: str,
    cwd: str | Path | None = None,
    source: str = "manual",
) -> QuickSnapshot:
    repo_root = _resolve_repo_root(cwd)
    scope = _resolve_scope(repo_root, project_id)
    _require_btrfs_subvolume(scope.path)

    oid = _head_oid(repo_root)
    if oid is None:
        raise SnapshotError("Snapshots require a repository with at least one commit.")

    snapshot_id = _snapshot_id(name)
    snapshot_path = _snapshot_destination(project_id, scope, snapshot_id)
    if snapshot_path.exists():
        raise SnapshotError(f"Snapshot path already exists: {snapshot_path}")

    _snapshot_subvolume(scope.path, snapshot_path, readonly=True)

    git_dir = _absolute_git_dir(repo_root)
    snapshot = QuickSnapshot(
        id=snapshot_id,
        name=name or None,
        project_id=project_id,
        repo_root=str(repo_root),
        worktree_path=str(scope.path),
        scope_type=scope.scope_type,
        scope_name=scope.scope_name,
        snapshot_path=str(snapshot_path),
        branch=get_current_branch(repo_root),
        head_oid=oid,
        head_ref=_head_ref(repo_root),
        git_dir=str(git_dir),
        index_artifact_path=_copy_index_artifact(
            git_dir=git_dir,
            project_id=project_id,
            scope=scope,
            snapshot_id=snapshot_id,
        ),
        created_at=_now_iso(),
        source=source,
    )

    entries = _load_manifest(project_id, scope)
    entries.append(snapshot)
    _save_manifest(project_id, scope, entries)
    return snapshot


# ---------------------------------------------------------------------------
# Restore (destructive rollback)
# ---------------------------------------------------------------------------


def _rollback_swap(scope_path: Path, backup_path: Path) -> None:
    """Undo a failed subvolume swap — delete the new scope and restore backup."""
    if scope_path.exists():
        with contextlib.suppress(SnapshotError):
            _delete_subvolume(scope_path)
    backup_path.rename(scope_path)


def _atomic_subvolume_swap(
    scope: SnapshotScope,
    source_snapshot: Path,
    *,
    post_swap_fn: object | None = None,
) -> None:
    """Replace *scope.path* with a writable snapshot of *source_snapshot*.

    An optional *post_swap_fn* (callable with no args) runs after the
    snapshot is placed but before the old backup is deleted.
    """
    backup_path = scope.path.parent / f"{scope.path.name}.__rollback_old__"
    if backup_path.exists():
        raise SnapshotError(
            f"Rollback staging path already exists: {backup_path}. "
            "Clean it up before retrying."
        )

    original_cwd = Path.cwd()
    os.chdir(_safe_cwd_for_scope(scope.path))
    swap_ok = False
    scope.path.rename(backup_path)
    try:
        _snapshot_subvolume(source_snapshot, scope.path, readonly=False)
        if post_swap_fn:
            post_swap_fn()
        swap_ok = True
    except Exception:
        _rollback_swap(scope.path, backup_path)
        raise
    finally:
        if swap_ok:
            _delete_subvolume(backup_path)
        fallback = scope.path if scope.path.exists() else _safe_cwd_for_scope(scope.path)
        os.chdir(original_cwd if original_cwd.exists() else fallback)


def restore_snapshot(
    target: str,
    *,
    project_id: str,
    cwd: str | Path | None = None,
) -> QuickSnapshot:
    repo_root = _resolve_repo_root(cwd)
    scope = _resolve_scope(repo_root, project_id)
    if scope.scope_type != "lane":
        raise SnapshotError(
            "Destructive rollback is only allowed for task lanes. "
            "Use 'st recover' from a project snapshot instead."
        )

    entries = _load_manifest(project_id, scope)
    snapshot = _find_snapshot(target, entries)

    if snapshot.worktree_path != str(scope.path):
        raise SnapshotError(
            "Snapshot belongs to a different lane.\n"
            f"  snapshot: {snapshot.worktree_path}\n"
            f"  current:  {scope.path}"
        )
    if snapshot.scope_type != "lane":
        raise SnapshotError("Destructive rollback is only supported for lane snapshots.")

    if snapshot.branch and (current_branch := get_current_branch(repo_root)) and snapshot.branch != current_branch:
        raise SnapshotError(
            f"Snapshot belongs to branch '{snapshot.branch}', but current branch is '{current_branch}'."
        )

    source_snapshot = Path(snapshot.snapshot_path)
    if not source_snapshot.exists():
        raise SnapshotError(f"Snapshot path is missing: {source_snapshot}")

    def _post_swap():
        _restore_lane_git_state(repo_root, snapshot)

    _atomic_subvolume_swap(scope, source_snapshot, post_swap_fn=_post_swap)
    return _update_manifest_entries(
        entries, snapshot, project_id, scope, last_restored_at=_now_iso(),
    )


def restore_project_snapshot(
    target: str,
    *,
    project_id: str,
    cwd: str | Path | None = None,
) -> QuickSnapshot:
    """Destructively replace the current project root with a recorded project snapshot."""
    repo_root = _resolve_repo_root(cwd)
    scope = _resolve_scope(repo_root, project_id)
    if scope.scope_type != "project":
        raise SnapshotError("Project snapshot restore is only allowed from a project root.")

    entries = _load_manifest(project_id, scope)
    snapshot = _find_snapshot(target, entries)

    if snapshot.worktree_path != str(scope.path):
        raise SnapshotError(
            "Snapshot belongs to a different project root.\n"
            f"  snapshot: {snapshot.worktree_path}\n"
            f"  current:  {scope.path}"
        )
    if snapshot.scope_type != "project":
        raise SnapshotError("Project snapshot restore requires a project-scoped snapshot.")

    source_snapshot = Path(snapshot.snapshot_path)
    if not source_snapshot.exists():
        raise SnapshotError(f"Snapshot path is missing: {source_snapshot}")

    _atomic_subvolume_swap(scope, source_snapshot)
    return _update_manifest_entries(
        entries, snapshot, project_id, scope, last_restored_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# Recovery (non-destructive sibling creation)
# ---------------------------------------------------------------------------


def _cleanup_failed_recovery(
    canonical_root: Path, destination: Path, recovery_branch: str,
) -> None:
    """Best-effort cleanup after a failed lane recovery attempt."""
    if destination.exists():
        with contextlib.suppress(SnapshotError):
            _git(canonical_root, ["worktree", "remove", str(destination), "--force"])
        if destination.exists():
            _delete_subvolume(destination)
    with contextlib.suppress(SnapshotError):
        _git(canonical_root, ["branch", "-D", recovery_branch])


def _recover_lane(
    snapshot: QuickSnapshot,
    snapshot_path: Path,
    recovery_name: str,
    repo_root: Path,
    project_id: str,
) -> tuple[Path, str]:
    """Create a recovery lane worktree from a lane snapshot."""
    destination = get_lanes_base_dir(project_id) / recovery_name
    if destination.exists():
        raise SnapshotError(f"Recovery destination already exists: {destination}")

    canonical_root = _canonical_repo_root(repo_root)
    recovery_branch = _recovery_branch_name(snapshot, recovery_name)
    _btrfs(["subvolume", "create", str(destination)])
    try:
        _git(
            canonical_root,
            ["worktree", "add", str(destination), "-b", recovery_branch, snapshot.head_oid or "HEAD"],
        )
        _rsync_snapshot_contents(snapshot_path, destination)
        recovered_git_dir = _absolute_git_dir(destination)
        if snapshot.index_artifact_path:
            shutil.copy2(snapshot.index_artifact_path, recovered_git_dir / "index")
    except Exception:
        _cleanup_failed_recovery(canonical_root, destination, recovery_branch)
        raise
    return destination, recovery_branch


def recover_snapshot(
    target: str,
    *,
    project_id: str,
    cwd: str | Path | None = None,
    name: str | None = None,
) -> QuickSnapshot:
    repo_root = _resolve_repo_root(cwd)
    scope = _resolve_scope(repo_root, project_id)
    entries = _load_manifest(project_id, scope)
    snapshot = _find_snapshot(target, entries)

    if snapshot.worktree_path != str(scope.path):
        raise SnapshotError(
            "Snapshot belongs to a different scope.\n"
            f"  snapshot: {snapshot.worktree_path}\n"
            f"  current:  {scope.path}"
        )

    snapshot_path = Path(snapshot.snapshot_path)
    if not snapshot_path.exists():
        raise SnapshotError(f"Snapshot path is missing: {snapshot_path}")

    rec_name = _recovery_name(name, snapshot)

    if snapshot.scope_type == "project":
        destination = get_projects_base_dir() / rec_name
        if destination.exists():
            raise SnapshotError(f"Recovery destination already exists: {destination}")
        _snapshot_subvolume(snapshot_path, destination, readonly=False)
        recovery_branch = get_current_branch(destination)
    else:
        destination, recovery_branch = _recover_lane(
            snapshot, snapshot_path, rec_name, repo_root, project_id,
        )

    return _update_manifest_entries(
        entries, snapshot, project_id, scope,
        last_recovered_at=_now_iso(),
        recovery_path=str(destination),
        recovery_branch=recovery_branch,
    )


# ---------------------------------------------------------------------------
# Lane deletion
# ---------------------------------------------------------------------------


def _unregister_worktree(inspection: LaneInspection, repo_root: Path) -> None:
    """Remove git worktree registration for a lane."""
    try:
        force_remove_worktree(inspection.lane_path, repo_root)
    except WorktreeError as exc:
        raise SnapshotError(f"Failed to remove git worktree registration: {exc}") from exc


def _delete_lane_branch(inspection: LaneInspection, repo_root: Path) -> None:
    """Delete the lane's tracking branch if it is safe to remove."""
    if not inspection.branch or inspection.branch in {"main", "master", "HEAD"}:
        return
    branch_ref = f"refs/heads/{inspection.branch}"
    branch_result = run_git(["show-ref", "--verify", branch_ref], cwd=repo_root, check=False)
    if branch_result.returncode != 0:
        return
    delete_result = run_git(
        ["branch", "-D", inspection.branch], cwd=repo_root, check=False,
    )
    if delete_result.returncode != 0:
        stderr = delete_result.stderr.strip() or delete_result.stdout.strip() or "unknown git error"
        raise SnapshotError(f"Failed to delete lane branch '{inspection.branch}': {stderr}")


def delete_lane(inspection: LaneInspection) -> None:
    """Delete a Btrfs lane, its snapshots, and metadata.

    Must be called from outside the lane directory (caller responsibility).
    """
    if inspection.is_git_worktree:
        repo_root = _resolve_lane_repo_root(inspection.lane_path)
        _unregister_worktree(inspection, repo_root)
        _delete_lane_branch(inspection, repo_root)

    for snap_path in inspection.snapshot_paths:
        _delete_subvolume(snap_path)

    if inspection.snapshot_dir and inspection.snapshot_dir.exists():
        with contextlib.suppress(OSError):
            inspection.snapshot_dir.rmdir()

    try:
        _delete_subvolume(inspection.lane_path)
    except SnapshotError as exc:
        message = str(exc)
        if "Invalid argument" not in message and "Not a Btrfs subvolume" not in message:
            raise
        if inspection.lane_path.is_dir():
            shutil.rmtree(inspection.lane_path, ignore_errors=False)
        elif inspection.lane_path.exists():
            inspection.lane_path.unlink()

    if inspection.manifest_dir and inspection.manifest_dir.exists():
        shutil.rmtree(inspection.manifest_dir, ignore_errors=True)

    with contextlib.suppress(Exception):
        from .checkpoint import remove_checkpoint_for_worktree_path

        remove_checkpoint_for_worktree_path(
            inspection.lane_path,
            project_id=inspection.project_id,
        )


def delete_orphaned_snapshots(orphan: OrphanedSnapshotDir) -> None:
    """Delete orphaned snapshot subvolumes and metadata."""
    for snap_path in orphan.snapshot_paths:
        _delete_subvolume(snap_path)

    if orphan.snapshot_dir.exists():
        with contextlib.suppress(OSError):
            orphan.snapshot_dir.rmdir()

    if orphan.manifest_dir and orphan.manifest_dir.exists():
        shutil.rmtree(orphan.manifest_dir, ignore_errors=True)


def delete_snapshot_residue(residue: SnapshotResidue) -> None:
    """Delete one legacy snapshot residue target."""
    if residue.residue_type == "legacy-snapshot-root":
        try:
            _delete_subvolume(residue.path)
        except SnapshotError as exc:
            message = str(exc)
            if "Invalid argument" not in message and "Not a Btrfs subvolume" not in message:
                raise
        if not residue.path.exists():
            return

    if residue.path.is_dir():
        shutil.rmtree(residue.path, ignore_errors=False)
    elif residue.path.exists():
        residue.path.unlink()


# ---------------------------------------------------------------------------
# Public aliases for cross-module use (autosnapshot.py).
# Keep underscore originals for backward compat with tests that monkeypatch them.
# ---------------------------------------------------------------------------
resolve_scope = _resolve_scope
load_manifest = _load_manifest
save_manifest = _save_manifest
delete_subvolume = _delete_subvolume
require_workspaces = _require_workspaces
require_btrfs_subvolume = _require_btrfs_subvolume

__all__ = [
    "LaneInspection",
    "OrphanedSnapshotDir",
    "QuickSnapshot",
    "SnapshotError",
    "SnapshotResidue",
    "SnapshotScope",
    "SnapshotUsage",
    "capture_snapshot",
    "delete_lane",
    "delete_orphaned_snapshots",
    "delete_snapshot_residue",
    "delete_subvolume",
    "find_empty_lane_dirs",
    "find_legacy_manifest_dirs",
    "find_legacy_snapshot_roots",
    "find_orphaned_lane_manifest_dirs",
    "find_orphaned_snapshot_dirs",
    "find_snapshot_residue",
    "get_snapshot_usage",
    "inspect_lane",
    "list_snapshots",
    "load_manifest",
    "recover_snapshot",
    "require_btrfs_subvolume",
    "require_workspaces",
    "resolve_scope",
    "restore_project_snapshot",
    "restore_snapshot",
    "save_manifest",
]
