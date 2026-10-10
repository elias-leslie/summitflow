"""Btrfs-backed project snapshot and recovery helpers."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from .snapshots._cleanup import (
    SnapshotResidue,
    find_legacy_manifest_dirs,
    find_legacy_snapshot_roots,
    find_snapshot_residue,
)
from .snapshots._helpers import (
    _absolute_git_dir,
    _find_snapshot,
    _git,
    _head_oid,
    _head_ref,
    _now_iso,
    _parse_btrfs_du_raw,
    _require_workspaces,
    _resolve_repo_root,
    _resolve_scope,
    _safe_cwd_for_scope,
    _snapshot_id,
)
from .snapshots._manifest import (
    _copy_index_artifact,
    _load_manifest,
    _recovery_name,
    _save_manifest,
    _snapshot_destination,
    _update_manifest_entries,
)
from .snapshots._models import (
    QuickSnapshot,
    SnapshotError,
    SnapshotScope,
    SnapshotUsage,
)
from .snapshots._physical import (
    inventory_nested,
    latest_physical_point,
    physical_lock,
    recent,
    require_complete_project,
)
from .snapshots._saved_work import (
    apply_file,
    beneath,
    classifications,
    file_digest,
    git_transaction_clear,
    require_owned,
    safe_relative,
    scope_lock,
    source_digest,
)
from .workspace_paths import (
    get_projects_base_dir,
    get_workspace_snapshots_base_dir,
    get_workspaces_root,
)

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


def _require_readonly_point(path: Path) -> None:
    if _btrfs(["property", "get", str(path), "ro"]).stdout.strip() != "ro=true":
        raise SnapshotError(f"Captured point is not a verified read-only Btrfs subvolume: {path}")


def _delete_subvolume(path: Path) -> None:
    if not path.exists():
        return
    _btrfs(["subvolume", "delete", str(path)])


def _is_non_subvolume_error(error: SnapshotError) -> bool:
    message = str(error)
    return "Invalid argument" in message or "Not a Btrfs subvolume" in message


def _is_readonly_denial(error: SnapshotError) -> bool:
    # btrfs-progs always warns "cannot read default subvolume id: Operation not
    # permitted" unprivileged; only the destroy error identifies a denial.
    message = str(error)
    return any(f"Could not destroy subvolume/snapshot: {reason}" in message
               for reason in ("Read-only file system", "Operation not permitted"))


def _delete_rejected_point(path: Path) -> None:
    """Remove a just-created read-only point that capture did not accept."""
    try:
        _delete_subvolume(path)
    except SnapshotError as exc:
        if not _is_readonly_denial(exc):
            raise
        from .snapshots._pruning import delete_managed_readonly

        delete_managed_readonly(path)


def _try_delete_subvolume(path: Path) -> bool:
    try:
        _delete_subvolume(path)
    except SnapshotError as exc:
        if _is_non_subvolume_error(exc):
            return False
        if not _is_readonly_denial(exc):
            raise
        # user_subvol_rm_allowed cannot remove read-only points; reuse the
        # pruning root helper, which revalidates the leaf before deleting.
        from .snapshots._pruning import delete_readonly_residue

        delete_readonly_residue(path)
    return True


def _delete_nested_subvolumes(path: Path) -> None:
    if not path.is_dir():
        return
    children = [child for child in path.rglob("*") if child.is_dir()]
    for child in sorted(children, key=lambda item: len(item.parts), reverse=True):
        if child.exists():
            _try_delete_subvolume(child)


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


def _capture_boundary(project_path: Path) -> Path:
    """Find a real subvolume; never assume an ordinary project directory is one."""
    boundary = project_path
    workspaces = get_workspaces_root().resolve()
    while True:
        # Every Btrfs subvolume root has inode 256. `subvolume show`
        # requires tree-search privilege on some host mounts; stat does not.
        if boundary.stat().st_ino == 256:
            return boundary
        if boundary == workspaces or workspaces not in boundary.parents:
            raise SnapshotError(f"No Btrfs subvolume boundary within workspace: {project_path}")
        boundary = boundary.parent


def snapshot_project_tree(snapshot: QuickSnapshot) -> Path:
    relative = Path(snapshot.project_relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise SnapshotError("Invalid captured project path")
    return Path(snapshot.snapshot_path) / relative


def capture_snapshot(
    name: str | None, *, project_id: str, cwd: str | Path | None = None, source: str = "manual",
) -> QuickSnapshot:
    repo_root = _resolve_repo_root(cwd)
    scope = _resolve_scope(repo_root, project_id)
    _require_btrfs_subvolume(scope.path)
    with physical_lock(), scope_lock(project_id, scope):
        git_transaction_clear(repo_root)
        boundary = _capture_boundary(scope.path)
        nested = inventory_nested(boundary, project=repo_root)
        require_complete_project(boundary, repo_root, nested)
        previous = latest_physical_point(boundary) if source.startswith("auto-") else None
        reuse = previous is not None and recent(previous)
        captured_digest: str | None = None
        if previous is not None and reuse:
            _require_readonly_point(Path(previous.snapshot_path))
            if not previous.source_digest:
                raise SnapshotError("Deferred: latest shared boundary capture is incomplete; physical captures are bounded to one per 15 minutes")
            require_complete_project(boundary, repo_root, previous.nested_subvolumes)
            captured = Path(previous.snapshot_path) / repo_root.relative_to(boundary)
            # Live trees use the identity cache; captured trees are hashed once
            # with page cache released so a many-project sweep stays bounded.
            captured_digest = source_digest(captured, drop_cache=True) if captured.is_dir() else None
            if captured_digest is None or source_digest(repo_root, use_cache=True) != captured_digest or _head_oid(repo_root) != _head_oid(captured):
                raise SnapshotError("Deferred: shared boundary captured within 15 minutes does not contain these latest saved edits; one physical point per boundary/15 minutes, next sweep will retry")
            snapshot_id = previous.id
            snapshot_path = Path(previous.snapshot_path)
            captured_at = previous.created_at
            nested = previous.nested_subvolumes
        else:
            from app.tasks._retention_policy import HostRetentionPolicy
            policy = HostRetentionPolicy.from_env()
            free = shutil.disk_usage(boundary).free
            minimum = policy.pressure_min_free_gb * 1024 ** 3
            if free < minimum:
                raise SnapshotError(f"Skipped: shared boundary free space {free / 1024 ** 3:.2f} GiB below host reserve {policy.pressure_min_free_gb:.2f} GiB; whole-boundary capture unavailable")
            snapshot_id = _snapshot_id(name)
            snapshot_path = _snapshot_destination(project_id, scope, snapshot_id)
            if snapshot_path.exists():
                raise SnapshotError(f"Snapshot path already exists: {snapshot_path}")
            captured_at = _now_iso()
            reservation = QuickSnapshot(id=snapshot_id, name=name, project_id=project_id,
                repo_root=str(repo_root), scope_path=str(scope.path), scope_type=scope.scope_type,
                scope_name=scope.scope_name, snapshot_path=str(snapshot_path), branch=None,
                head_oid=None, head_ref=None, git_dir=str(snapshot_path / repo_root.relative_to(boundary) / ".git"),
                index_artifact_path=None, created_at=captured_at, source="auto-incomplete",
                capture_root=str(boundary), project_relative_path=repo_root.relative_to(boundary).as_posix(),
                nested_subvolumes=nested, deletion_error="Capture metadata pending")
            pending = _load_manifest(project_id, scope)
            pending.append(reservation)
            _save_manifest(project_id, scope, pending)
        snapshot = None
        try:
            if not reuse:
                _snapshot_subvolume(boundary, snapshot_path, readonly=True)
            captured = snapshot_path / repo_root.relative_to(boundary)
            require_complete_project(boundary, repo_root, inventory_nested(boundary, project=repo_root))
            git_transaction_clear(captured)
            git_transaction_clear(repo_root)
            oid = _head_oid(captured)
            if oid is None:
                raise SnapshotError("Snapshots require a repository with at least one commit.")
            git_dir = _absolute_git_dir(captured)
            captured_head_ref = _head_ref(captured)
            snapshot = QuickSnapshot(
                id=snapshot_id, name=name or None, project_id=project_id,
                repo_root=str(repo_root), scope_path=str(scope.path), scope_type=scope.scope_type,
                scope_name=scope.scope_name, snapshot_path=str(snapshot_path),
                branch=captured_head_ref.removeprefix("refs/heads/") if captured_head_ref else None, head_oid=oid, head_ref=captured_head_ref,
                git_dir=str(git_dir), index_artifact_path=_copy_index_artifact(
                    git_dir=git_dir, project_id=project_id, scope=scope, snapshot_id=snapshot_id),
                created_at=captured_at, source=source, capture_root=str(boundary),
                project_relative_path=repo_root.relative_to(boundary).as_posix(),
                source_digest=captured_digest or source_digest(captured, drop_cache=True),
                unfinished=bool(_git(captured, ["status", "--short", "--untracked-files=all"]).stdout.strip()),
                nested_subvolumes=nested, shared_capture=reuse,
            )
            existing = _load_manifest(project_id, scope)
            if reuse and any(entry.id == snapshot.id for entry in existing):
                raise SnapshotError("Skipped: saved source unchanged; existing view and recovery catalogue retained")
            entries = [entry for entry in existing if entry.id != snapshot.id]
            if source.startswith("auto-") and entries and entries[0].source_digest == snapshot.source_digest and entries[0].head_oid == snapshot.head_oid:
                raise SnapshotError("Skipped: saved source unchanged after capture")
            entries.append(snapshot)
            _save_manifest(project_id, scope, entries)
            return snapshot
        except Exception as capture_error:
            if reuse:
                raise
            try:
                _delete_rejected_point(snapshot_path)
            except Exception as deletion_error:
                # A failed physical cleanup must remain catalogued and retryable.
                if snapshot is None:
                    snapshot = QuickSnapshot(id=snapshot_id, name=name, project_id=project_id,
                        repo_root=str(repo_root), scope_path=str(scope.path), scope_type=scope.scope_type,
                        scope_name=scope.scope_name, snapshot_path=str(snapshot_path), branch=None,
                        head_oid=None, head_ref=None, git_dir=str(snapshot_path / repo_root.relative_to(boundary) / ".git"),
                        index_artifact_path=None, created_at=captured_at, source="auto-incomplete",
                        capture_root=str(boundary), project_relative_path=repo_root.relative_to(boundary).as_posix())
                snapshot.deletion_error = f"Capture not accepted: {capture_error}; cleanup failed: {deletion_error}"
                entries = [entry for entry in _load_manifest(project_id, scope) if entry.id != snapshot.id]
                entries.append(snapshot)
                _save_manifest(project_id, scope, entries)
                raise SnapshotError(snapshot.deletion_error) from deletion_error
            _save_manifest(project_id, scope, [entry for entry in _load_manifest(project_id, scope) if entry.id != snapshot_id])
            raise


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
    post_swap_fn: Callable[[], None] | None = None,
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
    return restore_project_snapshot(target, project_id=project_id, cwd=cwd)


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

    if snapshot.scope_path != str(scope.path):
        raise SnapshotError(
            "Snapshot belongs to a different project root.\n"
            f"  snapshot: {snapshot.scope_path}\n"
            f"  current:  {scope.path}"
        )
    if snapshot.scope_type != "project":
        raise SnapshotError("Project snapshot restore requires a project-scoped snapshot.")

    source_snapshot = Path(snapshot.snapshot_path)
    if not source_snapshot.exists():
        raise SnapshotError(f"Snapshot path is missing: {source_snapshot}")

    if (snapshot.capture_root and Path(snapshot.capture_root) != scope.path) or scope.path == get_workspaces_root().resolve() or Path("/srv/workspaces").resolve() in scope.path.parents:
        raise SnapshotError("Whole workspace/production rollback is refused; use selected-file recovery")
    _atomic_subvolume_swap(scope, source_snapshot)
    return _update_manifest_entries(
        entries, snapshot, project_id, scope, last_restored_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# Recovery (non-destructive sibling creation)
# ---------------------------------------------------------------------------


def _cleanup_failed_recovery(
    destination: Path,
) -> None:
    """Best-effort cleanup after a failed recovery attempt."""
    if destination.exists():
        with contextlib.suppress(SnapshotError):
            _delete_subvolume(destination)
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=False)

def list_snapshots(
    *,
    project_id: str,
    cwd: str | Path | None = None,
) -> list[QuickSnapshot]:
    repo_root = _resolve_repo_root(cwd)
    scope = _resolve_scope(repo_root, project_id)
    return _load_manifest(project_id, scope)


def recovery_catalogue(snapshot: QuickSnapshot) -> list[dict]:
    """Adopt old manifests without losing the physical copy they already record."""
    if not snapshot.recovery_copies and snapshot.recovery_path:
        root = Path(snapshot.recovery_path)
        for _ in Path(snapshot.project_relative_path).parts:
            root = root.parent
        snapshot.recovery_copies.append({"root_path": str(root), "project_path": snapshot.recovery_path,
            "created_at": snapshot.last_recovered_at or snapshot.created_at,
            "active": snapshot.recovery_active,
            "released_at": None if snapshot.recovery_active else snapshot.last_recovered_at or snapshot.created_at,
            "deleted_at": None, "deletion_error": None})
    return snapshot.recovery_copies


def cleanup_recovery_copies(snapshot: QuickSnapshot, *, delete_fn: Callable[[Path], None], dry_run: bool = False) -> list[str]:
    """Clean released copies independently of point retention; preserve failed roots."""
    candidates = []
    for copy in recovery_catalogue(snapshot):
        if copy.get("active") or copy.get("deleted_at") or not copy.get("released_at"):
            continue
        root = Path(copy["root_path"])
        candidates.append(str(root))
        if dry_run:
            continue
        try:
            store = get_workspace_snapshots_base_dir().resolve() / "recoveries" / snapshot.project_id
            legacy = get_projects_base_dir().resolve()
            valid_new = root.parent.resolve() == store and root.resolve() != Path(snapshot.scope_path).resolve()
            valid_legacy = root.parent.resolve() == legacy and root.name.startswith("recover-") and root.resolve() != Path(snapshot.scope_path).resolve()
            if root.is_symlink() or not (valid_new or valid_legacy):
                raise SnapshotError(f"Recovery cleanup root is outside its managed catalogue store: {root}")
            delete_fn(root)
            if root.exists():
                raise SnapshotError(f"Physical recovery copy remains: {root}")
            copy["deleted_at"] = _now_iso()
            copy["deletion_error"] = None
            if snapshot.recovery_path == copy["project_path"]:
                snapshot.recovery_path = None
                snapshot.recovery_branch = None
        except Exception as exc:
            copy["deletion_error"] = str(exc)
    return candidates


def recover_snapshot(
    target: str, *, project_id: str, cwd: str | Path | None = None, name: str | None = None,
) -> QuickSnapshot:
    repo_root = _resolve_repo_root(cwd)
    scope = _resolve_scope(repo_root, project_id)
    with scope_lock(project_id, scope):
        entries = _load_manifest(project_id, scope)
        snapshot = _find_snapshot(target, entries)
        if snapshot.scope_path != str(scope.path) or snapshot.scope_type != "project":
            raise SnapshotError("Recovery requires the matching project scope")
        copies = recovery_catalogue(snapshot)
        if any(not copy.get("deleted_at") for copy in copies):
            raise SnapshotError("Recovery copy already catalogued; release and prune its tracked copy before creating another")
        if not Path(snapshot.snapshot_path).exists():
            raise SnapshotError(f"Snapshot path is missing: {snapshot.snapshot_path}")
        _require_readonly_point(Path(snapshot.snapshot_path))
        store = get_workspace_snapshots_base_dir() / "recoveries" / project_id
        store.mkdir(parents=True, exist_ok=True)
        destination = store / _recovery_name(name, snapshot)
        if destination.exists():
            raise SnapshotError(f"Recovery destination already exists: {destination}")
        actual = destination / snapshot.project_relative_path
        record = {"root_path": str(destination), "project_path": str(actual), "created_at": _now_iso(),
            "active": True, "released_at": None, "deleted_at": None, "deletion_error": None}
        # Reserve the catalogue row before physical creation. A failure cannot
        # create an anonymous copy that a second recovery silently overwrites.
        copies.append(record)
        snapshot.recovery_copies = copies
        snapshot.recovery_active = True
        _save_manifest(project_id, scope, entries)
        try:
            _snapshot_subvolume(Path(snapshot.snapshot_path), destination, readonly=True)
        except Exception as exc:
            record.update(active=False, released_at=_now_iso(), deletion_error=str(exc))
            snapshot.recovery_active = False
            snapshot.recovery_copies = copies
            _save_manifest(project_id, scope, entries)
            raise
        return _update_manifest_entries(entries, snapshot, project_id, scope,
            last_recovered_at=record["created_at"], recovery_path=str(actual), recovery_branch=snapshot.branch,
            recovery_active=True, pin_reason=snapshot.pin_reason or "active recovery", pin_until=snapshot.pin_until,
            recovery_copies=copies)


def recovery_preview(target: str, *, project_id: str, paths: list[str], owned_paths: list[str], cwd: str | Path | None = None, verify_ownership: bool = True) -> dict:
    root = _resolve_repo_root(cwd)
    scope = _resolve_scope(root, project_id)
    snapshot = _find_snapshot(target, _load_manifest(project_id, scope))
    if snapshot.scope_path != str(scope.path):
        raise SnapshotError("Snapshot scope mismatch")
    selected = sorted(set(safe_relative(p) for p in paths))
    if not selected:
        raise SnapshotError("Select at least one file")
    if verify_ownership:
        require_owned(project_id, root, selected, owned_paths)
    captured = snapshot_project_tree(snapshot)
    rules = classifications(root)
    captured_rules = classifications(captured)
    files = []
    for item in selected:
        if beneath(item, rules["durable_data"] + captured_rules["durable_data"]):
            raise SnapshotError(f"Durable data requires a separate application restore: {item}")
        for base in (root, captured):
            if any((base / Path(item).parents[i]).is_symlink() for i in range(len(Path(item).parents))):
                raise SnapshotError(f"Symlink parent blocks recovery: {item}")
        files.append({"path": item, "current_digest": file_digest(root / item), "captured_digest": file_digest(captured / item)})
    payload = {"snapshot_id": snapshot.id, "project_id": project_id, "scope_path": str(root), "files": files}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return {**payload, "preview_digest": digest}


def apply_recovery(target: str, *, project_id: str, paths: list[str], owned_paths: list[str], preview_digest: str, cwd: str | Path | None = None) -> dict:
    root = _resolve_repo_root(cwd)
    scope = _resolve_scope(root, project_id)
    with scope_lock(project_id, scope):
        git_transaction_clear(root)
        preview = recovery_preview(target, project_id=project_id, paths=paths, owned_paths=owned_paths, cwd=root)
        if preview["preview_digest"] != preview_digest:
            raise SnapshotError("Intervening edits changed recovery preview; preview again")
        snapshot = _find_snapshot(target, _load_manifest(project_id, scope))
        captured = snapshot_project_tree(snapshot)
        for item in preview["files"]:
            require_owned(project_id, root, [item["path"]], owned_paths)
            apply_file(root, item["path"], captured / item["path"], item["current_digest"])
        return {"ok": True, "applied": [f["path"] for f in preview["files"]]}


def release_recovery(target: str, *, project_id: str, cwd: str | Path | None = None) -> QuickSnapshot:
    scope = _resolve_scope(_resolve_repo_root(cwd), project_id)
    with scope_lock(project_id, scope):
        entries = _load_manifest(project_id, scope)
        snapshot = _find_snapshot(target, entries)
        copies = recovery_catalogue(snapshot)
        for copy in copies:
            if not copy.get("deleted_at"):
                copy["active"] = False
                copy["released_at"] = copy.get("released_at") or _now_iso()
        return _update_manifest_entries(entries, snapshot, project_id, scope, recovery_active=False,
            pin_reason=None if snapshot.pin_reason == "active recovery" else snapshot.pin_reason,
            pin_until=None if snapshot.pin_reason == "active recovery" else snapshot.pin_until,
            recovery_copies=copies)


def delete_snapshot_residue(residue: SnapshotResidue) -> None:
    """Delete one legacy snapshot residue target."""
    if residue.residue_type == "legacy-snapshot-root":
        _delete_nested_subvolumes(residue.path)
        _try_delete_subvolume(residue.path)
        if not residue.path.exists():
            return

    if residue.path.is_dir():
        shutil.rmtree(residue.path, ignore_errors=False)
        if residue.path.exists():
            residue.path.rmdir()
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
    "QuickSnapshot",
    "SnapshotError",
    "SnapshotResidue",
    "SnapshotScope",
    "SnapshotUsage",
    "capture_snapshot",
    "delete_snapshot_residue",
    "delete_subvolume",
    "find_legacy_manifest_dirs",
    "find_legacy_snapshot_roots",
    "find_snapshot_residue",
    "get_snapshot_usage",
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
