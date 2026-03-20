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

import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .worktree_git import WorktreeError, get_current_branch, get_repo_root
from .worktree_paths import (
    get_lanes_base_dir,
    get_projects_base_dir,
    get_workspace_snapshots_base_dir,
    workspaces_root_available,
)


class SnapshotError(Exception):
    """Raised when a snapshot operation cannot complete safely."""


@dataclass(frozen=True)
class SnapshotScope:
    """Resolved Btrfs scope for the current checkout."""

    scope_type: str
    scope_name: str
    path: Path


@dataclass
class QuickSnapshot:
    """Manifest entry for a Btrfs-backed lane or project snapshot."""

    id: str
    name: str | None
    project_id: str
    repo_root: str
    worktree_path: str
    scope_type: str
    scope_name: str
    snapshot_path: str
    branch: str | None
    head_oid: str | None
    head_ref: str | None
    git_dir: str
    index_artifact_path: str | None
    created_at: str
    backend: str = "btrfs"
    last_restored_at: str | None = None
    last_recovered_at: str | None = None
    recovery_path: str | None = None
    recovery_branch: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QuickSnapshot:
        return cls(
            id=str(data["id"]),
            name=str(data["name"]) if data.get("name") else None,
            project_id=str(data["project_id"]),
            repo_root=str(data["repo_root"]),
            worktree_path=str(data["worktree_path"]),
            scope_type=str(data["scope_type"]),
            scope_name=str(data["scope_name"]),
            snapshot_path=str(data["snapshot_path"]),
            branch=str(data["branch"]) if data.get("branch") else None,
            head_oid=str(data["head_oid"]) if data.get("head_oid") else None,
            head_ref=str(data["head_ref"]) if data.get("head_ref") else None,
            git_dir=str(data["git_dir"]),
            index_artifact_path=(
                str(data["index_artifact_path"]) if data.get("index_artifact_path") else None
            ),
            created_at=str(data["created_at"]),
            backend=str(data.get("backend") or "btrfs"),
            last_restored_at=(
                str(data["last_restored_at"]) if data.get("last_restored_at") else None
            ),
            last_recovered_at=(
                str(data["last_recovered_at"]) if data.get("last_recovered_at") else None
            ),
            recovery_path=str(data["recovery_path"]) if data.get("recovery_path") else None,
            recovery_branch=(
                str(data["recovery_branch"]) if data.get("recovery_branch") else None
            ),
        )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sanitize_label(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-")
    return cleaned or "snapshot"


def _snapshot_id(name: str | None) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    if name:
        return f"{timestamp}-{_sanitize_label(name)[:40]}-{suffix}"
    return f"{timestamp}-{suffix}"


def _git(
    repo_root: Path,
    args: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=check,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or str(exc)
        raise SnapshotError(f"Git command failed: git {' '.join(args)}\n{stderr}") from exc
    except OSError as exc:
        raise SnapshotError(f"Failed to run git {' '.join(args)}: {exc}") from exc


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


def _resolve_repo_root(cwd: str | Path | None = None) -> Path:
    try:
        return get_repo_root(Path(cwd) if cwd is not None else None)
    except WorktreeError as exc:
        raise SnapshotError(str(exc)) from exc


def _head_oid(repo_root: Path) -> str | None:
    result = _git(repo_root, ["rev-parse", "--verify", "HEAD"], check=False)
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def _head_ref(repo_root: Path) -> str | None:
    result = _git(repo_root, ["symbolic-ref", "-q", "HEAD"], check=False)
    if result.returncode == 0:
        return result.stdout.strip() or None
    return None


def _absolute_git_dir(repo_root: Path) -> Path:
    result = _git(repo_root, ["rev-parse", "--path-format=absolute", "--git-dir"])
    return Path(result.stdout.strip()).resolve()


def _absolute_git_common_dir(repo_root: Path) -> Path:
    result = _git(repo_root, ["rev-parse", "--path-format=absolute", "--git-common-dir"])
    return Path(result.stdout.strip()).resolve()


def _canonical_repo_root(repo_root: Path) -> Path:
    common_dir = _absolute_git_common_dir(repo_root)
    if common_dir.name == ".git":
        return common_dir.parent.resolve()
    return common_dir.resolve()


def _require_workspaces() -> None:
    if not workspaces_root_available():
        raise SnapshotError(
            "Shared Btrfs workspaces are not available on this host. "
            "Mount /srv/workspaces first."
        )


def _resolve_scope(repo_root: Path, project_id: str) -> SnapshotScope:
    _require_workspaces()
    resolved_root = repo_root.resolve()

    project_path = get_projects_base_dir(project_id).resolve()
    if resolved_root == project_path:
        return SnapshotScope("project", project_id, resolved_root)

    lanes_base = get_lanes_base_dir(project_id).resolve()
    try:
        relative = resolved_root.relative_to(lanes_base)
    except ValueError as exc:
        raise SnapshotError(
            "Snapshots only work inside Btrfs-backed project roots or task lanes.\n"
            f"  current: {resolved_root}\n"
            f"  project: {project_path}\n"
            f"  lanes:   {lanes_base}"
        ) from exc

    if len(relative.parts) != 1:
        raise SnapshotError(
            "Expected the current lane to be a direct child of the Btrfs lanes root.\n"
            f"  current: {resolved_root}\n"
            f"  lanes:   {lanes_base}"
        )

    return SnapshotScope("lane", relative.parts[0], resolved_root)


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


def _scope_key(scope: SnapshotScope) -> str:
    return f"{scope.scope_type}-{_sanitize_label(scope.scope_name)}"


def _manifest_dir(project_id: str, scope: SnapshotScope) -> Path:
    target = Path.home() / ".local" / "share" / "st" / "snaps" / project_id / _scope_key(scope)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _manifest_path(project_id: str, scope: SnapshotScope) -> Path:
    return _manifest_dir(project_id, scope) / "manifest.json"


def _artifacts_dir(project_id: str, scope: SnapshotScope, snapshot_id: str) -> Path:
    target = _manifest_dir(project_id, scope) / "artifacts" / snapshot_id
    target.mkdir(parents=True, exist_ok=True)
    return target


def _load_manifest(project_id: str, scope: SnapshotScope) -> list[QuickSnapshot]:
    path = _manifest_path(project_id, scope)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"Snapshot manifest is invalid: {path}") from exc
    if not isinstance(raw, list):
        raise SnapshotError(f"Snapshot manifest has unexpected format: {path}")
    entries = [QuickSnapshot.from_dict(item) for item in raw if isinstance(item, dict)]
    entries.sort(key=lambda entry: entry.created_at, reverse=True)
    return entries


def _save_manifest(project_id: str, scope: SnapshotScope, entries: list[QuickSnapshot]) -> None:
    path = _manifest_path(project_id, scope)
    ordered = sorted(entries, key=lambda entry: entry.created_at, reverse=True)
    path.write_text(
        json.dumps([entry.to_dict() for entry in ordered], indent=2),
        encoding="utf-8",
    )


def _snapshot_destination(project_id: str, scope: SnapshotScope, snapshot_id: str) -> Path:
    root = get_workspace_snapshots_base_dir(project_id) / f"{scope.scope_type}s" / _sanitize_label(
        scope.scope_name
    )
    root.mkdir(parents=True, exist_ok=True)
    return root / snapshot_id


def _copy_index_artifact(
    *,
    git_dir: Path,
    project_id: str,
    scope: SnapshotScope,
    snapshot_id: str,
) -> str | None:
    index_path = git_dir / "index"
    if not index_path.exists():
        return None
    artifact_path = _artifacts_dir(project_id, scope, snapshot_id) / "index"
    shutil.copy2(index_path, artifact_path)
    return str(artifact_path)


def _find_snapshot(target: str, entries: list[QuickSnapshot]) -> QuickSnapshot:
    if not entries:
        raise SnapshotError("No snapshots found for the current scope.")

    if re.fullmatch(r"-\d+", target):
        idx = abs(int(target)) - 1
        if idx >= len(entries):
            raise SnapshotError(f"Snapshot index {target} is out of range.")
        return entries[idx]

    exact_id = next((entry for entry in entries if entry.id == target), None)
    if exact_id:
        return exact_id

    named = next((entry for entry in entries if entry.name == target), None)
    if named:
        return named

    prefix = next((entry for entry in entries if entry.id.startswith(target)), None)
    if prefix:
        return prefix

    raise SnapshotError(f"Snapshot '{target}' was not found for the current scope.")


def _snapshot_subvolume(source: Path, destination: Path, *, readonly: bool) -> None:
    args = ["subvolume", "snapshot"]
    if readonly:
        args.append("-r")
    args.extend([str(source), str(destination)])
    _btrfs(args)


def _delete_subvolume(path: Path) -> None:
    if not path.exists():
        return
    with suppress_snapshot_error():
        _btrfs(["property", "set", str(path), "ro", "false"])
    _btrfs(["subvolume", "delete", str(path)])


class suppress_snapshot_error:
    """Suppress SnapshotError for cleanup best-effort paths."""

    def __enter__(self) -> suppress_snapshot_error:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return isinstance(exc, SnapshotError)


def _safe_cwd_for_scope(scope_path: Path) -> Path:
    workspaces_root = scope_path.parents[2] if len(scope_path.parents) >= 3 else Path.home()
    return workspaces_root if workspaces_root.exists() else Path.home()


def _restore_lane_git_state(repo_root: Path, snapshot: QuickSnapshot) -> None:
    if snapshot.head_oid is None:
        raise SnapshotError("Snapshot is missing the recorded HEAD commit.")

    git_dir = Path(snapshot.git_dir)
    head_file = git_dir / "HEAD"

    if snapshot.head_ref:
        _git(repo_root, ["update-ref", snapshot.head_ref, snapshot.head_oid])
        head_file.write_text(f"ref: {snapshot.head_ref}\n", encoding="utf-8")
    else:
        head_file.write_text(f"{snapshot.head_oid}\n", encoding="utf-8")

    if snapshot.index_artifact_path:
        artifact_path = Path(snapshot.index_artifact_path)
        if not artifact_path.exists():
            raise SnapshotError(f"Snapshot index artifact is missing: {artifact_path}")
        shutil.copy2(artifact_path, git_dir / "index")


def _recovery_name(name: str | None, snapshot: QuickSnapshot) -> str:
    if name:
        return _sanitize_label(name)
    stem = snapshot.name or snapshot.id
    return _sanitize_label(f"recover-{stem}")[:80]


def _recovery_branch_name(snapshot: QuickSnapshot, recovery_name: str) -> str:
    seed = snapshot.scope_name if snapshot.scope_type == "lane" else snapshot.project_id
    return _sanitize_label(f"recover/{seed}/{recovery_name}")[:120]


def _rsync_snapshot_contents(snapshot_path: Path, destination: Path) -> None:
    try:
        subprocess.run(
            [
                "rsync",
                "-a",
                "--delete",
                "--exclude=.git",
                f"{snapshot_path}/",
                f"{destination}/",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or str(exc)
        raise SnapshotError(f"Failed to sync recovered snapshot contents:\n{stderr}") from exc
    except OSError as exc:
        raise SnapshotError(f"Failed to run rsync for snapshot recovery: {exc}") from exc


def capture_snapshot(
    name: str | None,
    *,
    project_id: str,
    cwd: str | Path | None = None,
) -> QuickSnapshot:
    repo_root = _resolve_repo_root(cwd)
    scope = _resolve_scope(repo_root, project_id)
    _require_btrfs_subvolume(scope.path)

    head_oid = _head_oid(repo_root)
    if head_oid is None:
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
        head_oid=head_oid,
        head_ref=_head_ref(repo_root),
        git_dir=str(git_dir),
        index_artifact_path=_copy_index_artifact(
            git_dir=git_dir,
            project_id=project_id,
            scope=scope,
            snapshot_id=snapshot_id,
        ),
        created_at=_now_iso(),
    )

    entries = _load_manifest(project_id, scope)
    entries.append(snapshot)
    _save_manifest(project_id, scope, entries)
    return snapshot


def list_snapshots(
    *,
    project_id: str,
    cwd: str | Path | None = None,
) -> list[QuickSnapshot]:
    repo_root = _resolve_repo_root(cwd)
    scope = _resolve_scope(repo_root, project_id)
    return _load_manifest(project_id, scope)


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

    backup_path = scope.path.parent / f"{scope.path.name}.__rollback_old__"
    if backup_path.exists():
        raise SnapshotError(
            f"Rollback staging path already exists: {backup_path}. "
            "Clean it up before retrying."
        )

    original_cwd = Path.cwd()
    os.chdir(_safe_cwd_for_scope(scope.path))
    try:
        scope.path.rename(backup_path)
        try:
            _snapshot_subvolume(source_snapshot, scope.path, readonly=False)
            _restore_lane_git_state(repo_root, snapshot)
        except Exception:
            if scope.path.exists():
                _delete_subvolume(scope.path)
            backup_path.rename(scope.path)
            raise
        _delete_subvolume(backup_path)
    finally:
        os.chdir(original_cwd if original_cwd.exists() else scope.path)

    updated_entries: list[QuickSnapshot] = []
    restored_at = _now_iso()
    for entry in entries:
        if entry.id == snapshot.id:
            entry = QuickSnapshot.from_dict({**entry.to_dict(), "last_restored_at": restored_at})
            snapshot = entry
        updated_entries.append(entry)
    _save_manifest(project_id, scope, updated_entries)
    return snapshot


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

    recovery_name = _recovery_name(name, snapshot)
    if snapshot.scope_type == "project":
        destination = get_projects_base_dir() / recovery_name
        if destination.exists():
            raise SnapshotError(f"Recovery destination already exists: {destination}")
        _snapshot_subvolume(snapshot_path, destination, readonly=False)
        recovery_branch = get_current_branch(destination)
    else:
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
            if destination.exists():
                with suppress_snapshot_error():
                    _git(canonical_root, ["worktree", "remove", str(destination), "--force"])
                if destination.exists():
                    _delete_subvolume(destination)
            with suppress_snapshot_error():
                _git(canonical_root, ["branch", "-D", recovery_branch])
            raise

    updated_entries: list[QuickSnapshot] = []
    recovered_at = _now_iso()
    for entry in entries:
        if entry.id == snapshot.id:
            entry = QuickSnapshot.from_dict(
                {
                    **entry.to_dict(),
                    "last_recovered_at": recovered_at,
                    "recovery_path": str(destination),
                    "recovery_branch": recovery_branch,
                }
            )
            snapshot = entry
        updated_entries.append(entry)
    _save_manifest(project_id, scope, updated_entries)
    return snapshot


__all__ = [
    "QuickSnapshot",
    "SnapshotError",
    "capture_snapshot",
    "list_snapshots",
    "recover_snapshot",
    "restore_snapshot",
]
