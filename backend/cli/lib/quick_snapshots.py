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

from .worktree_git import WorktreeError, get_current_branch, get_repo_root, run_git
from .worktree_helpers import force_remove_worktree
from .worktree_ops import get_worktree_branch
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
    source: str = "manual"
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
            source=str(data.get("source") or "manual"),
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


@dataclass(frozen=True)
class SnapshotUsage:
    """Btrfs usage statistics for a single snapshot subvolume."""

    total_bytes: int
    exclusive_bytes: int
    shared_bytes: int

    def to_dict(self) -> dict[str, int]:
        return {
            "total_bytes": self.total_bytes,
            "exclusive_bytes": self.exclusive_bytes,
            "shared_bytes": self.shared_bytes,
        }


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


def _parse_btrfs_du_raw(output: str, expected_path: Path) -> SnapshotUsage:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if len(lines) < 2:
        raise SnapshotError(
            "Unable to parse snapshot usage output from btrfs filesystem du.\n"
            f"  path: {expected_path}"
        )

    raw_parts = lines[-1].split(maxsplit=3)
    if len(raw_parts) != 4:
        raise SnapshotError(
            "Unexpected btrfs filesystem du output format.\n"
            f"  path: {expected_path}\n"
            f"  line: {lines[-1]}"
        )

    total_raw, exclusive_raw, shared_raw, resolved_path = raw_parts
    if Path(resolved_path).resolve() != expected_path.resolve():
        raise SnapshotError(
            "Btrfs usage output did not match the requested snapshot path.\n"
            f"  expected: {expected_path}\n"
            f"  actual:   {resolved_path}"
        )

    return SnapshotUsage(
        total_bytes=int(total_raw),
        exclusive_bytes=int(exclusive_raw),
        shared_bytes=int(shared_raw),
    )


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
    source: str = "manual",
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
        source=source,
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


@dataclass(frozen=True)
class LaneInspection:
    """Result of inspecting a Btrfs lane for cleanup."""

    project_id: str
    lane_name: str
    lane_path: Path
    is_git_worktree: bool
    branch: str | None
    snapshot_paths: list[Path]
    snapshot_dir: Path | None
    manifest_dir: Path | None

    @property
    def total_items(self) -> int:
        """Number of subvolumes that will be deleted (snapshots + lane)."""
        return len(self.snapshot_paths) + 1


@dataclass(frozen=True)
class OrphanedSnapshotDir:
    """Snapshot directory whose parent lane no longer exists."""

    project_id: str
    lane_name: str
    snapshot_dir: Path
    snapshot_paths: list[Path]
    manifest_dir: Path | None

    @property
    def total_items(self) -> int:
        return len(self.snapshot_paths)


@dataclass(frozen=True)
class SnapshotResidue:
    """Legacy snapshot state that falls outside the managed lane/project layout."""

    project_id: str | None
    residue_name: str
    path: Path
    residue_type: str

    @property
    def total_items(self) -> int:
        return 1


def _snapshot_manifest_root(project_id: str) -> Path:
    return Path.home() / ".local" / "share" / "st" / "snaps" / project_id


def find_orphaned_lane_manifest_dirs(project_id: str) -> list[SnapshotResidue]:
    """Find lane manifest dirs whose lane and lane snapshots are both gone."""
    manifest_root = _snapshot_manifest_root(project_id)
    if not manifest_root.is_dir():
        return []

    lanes_base = get_lanes_base_dir(project_id)
    snap_lanes_base = get_workspace_snapshots_base_dir(project_id) / "lanes"
    residues: list[SnapshotResidue] = []

    for entry in sorted(manifest_root.iterdir()):
        if not entry.is_dir() or not entry.name.startswith("lane-"):
            continue
        lane_name = entry.name.removeprefix("lane-")
        if (lanes_base / lane_name).exists():
            continue
        if (snap_lanes_base / lane_name).exists():
            continue
        residues.append(
            SnapshotResidue(
                project_id=project_id,
                residue_name=lane_name,
                path=entry,
                residue_type="orphan-lane-manifest",
            )
        )

    return residues


def find_empty_lane_dirs(project_id: str) -> list[SnapshotResidue]:
    """Find empty non-worktree lane directories left behind after lane cleanup."""
    lanes_base = get_lanes_base_dir(project_id)
    if not lanes_base.is_dir():
        return []

    residues: list[SnapshotResidue] = []
    for entry in sorted(lanes_base.iterdir()):
        if not entry.is_dir():
            continue
        if (entry / ".git").exists():
            continue
        try:
            next(entry.iterdir())
        except StopIteration:
            residues.append(
                SnapshotResidue(
                    project_id=project_id,
                    residue_name=entry.name,
                    path=entry,
                    residue_type="empty-lane-dir",
                )
            )

    return residues


def find_legacy_manifest_dirs(project_id: str) -> list[SnapshotResidue]:
    """Find legacy snapshot manifest dirs that do not match current scope keys."""
    manifest_root = _snapshot_manifest_root(project_id)
    if not manifest_root.is_dir():
        return []

    residues: list[SnapshotResidue] = []
    for entry in sorted(manifest_root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("lane-") or entry.name.startswith("project-"):
            continue
        residues.append(
            SnapshotResidue(
                project_id=project_id,
                residue_name=entry.name,
                path=entry,
                residue_type="legacy-manifest",
            )
        )

    return residues


def find_legacy_snapshot_roots(
    managed_project_ids: list[str],
    *,
    project_id: str | None = None,
) -> list[SnapshotResidue]:
    """Find unmanaged top-level snapshot roots under /srv/workspaces/.snapshots."""
    _require_workspaces()
    snapshots_root = get_workspace_snapshots_base_dir()
    managed = set(managed_project_ids)
    residues: list[SnapshotResidue] = []

    for entry in sorted(snapshots_root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in managed:
            continue

        owner_project_id = next(
            (pid for pid in managed_project_ids if entry.name.startswith(f"{pid}-")),
            None,
        )
        if project_id is not None and owner_project_id != project_id:
            continue

        residues.append(
            SnapshotResidue(
                project_id=owner_project_id,
                residue_name=entry.name,
                path=entry,
                residue_type="legacy-snapshot-root",
            )
        )

    return residues


def find_snapshot_residue(
    managed_project_ids: list[str],
    *,
    project_id: str | None = None,
) -> list[SnapshotResidue]:
    """Find snapshot-related residue outside the current managed cleanup paths."""
    residues: list[SnapshotResidue] = []
    residues.extend(find_legacy_snapshot_roots(managed_project_ids, project_id=project_id))

    project_ids = [project_id] if project_id else managed_project_ids
    for pid in project_ids:
        residues.extend(find_empty_lane_dirs(pid))
        residues.extend(find_orphaned_lane_manifest_dirs(pid))
        residues.extend(find_legacy_manifest_dirs(pid))

    return sorted(
        residues,
        key=lambda residue: (
            residue.project_id or "",
            residue.residue_type,
            residue.residue_name,
        ),
    )


def delete_snapshot_residue(residue: SnapshotResidue) -> None:
    """Delete one legacy snapshot residue target."""
    if residue.residue_type == "legacy-snapshot-root":
        try:
            _delete_subvolume(residue.path)
            return
        except SnapshotError as exc:
            message = str(exc)
            if "Invalid argument" not in message and "Not a Btrfs subvolume" not in message:
                raise

    if residue.path.is_dir():
        shutil.rmtree(residue.path, ignore_errors=False)
    elif residue.path.exists():
        residue.path.unlink()


def find_orphaned_snapshot_dirs(project_id: str) -> list[OrphanedSnapshotDir]:
    """Find snapshot directories for lanes that no longer exist."""
    _require_workspaces()
    snap_lanes_base = get_workspace_snapshots_base_dir(project_id) / "lanes"
    if not snap_lanes_base.is_dir():
        return []

    lanes_base = get_lanes_base_dir(project_id)
    orphans: list[OrphanedSnapshotDir] = []

    for snap_dir in sorted(snap_lanes_base.iterdir()):
        if not snap_dir.is_dir():
            continue
        # Check if the corresponding lane still exists
        lane_path = lanes_base / snap_dir.name
        if lane_path.exists():
            continue  # Lane exists — not orphaned

        snapshot_paths = sorted(p for p in snap_dir.iterdir() if p.is_dir())
        # Check for manifest dir
        manifest_base = (
            Path.home() / ".local" / "share" / "st" / "snaps"
            / project_id / f"lane-{snap_dir.name}"
        )
        orphans.append(OrphanedSnapshotDir(
            project_id=project_id,
            lane_name=snap_dir.name,
            snapshot_dir=snap_dir,
            snapshot_paths=snapshot_paths,
            manifest_dir=manifest_base if manifest_base.is_dir() else None,
        ))

    return orphans


def delete_orphaned_snapshots(orphan: OrphanedSnapshotDir) -> None:
    """Delete orphaned snapshot subvolumes and metadata."""
    for snap_path in orphan.snapshot_paths:
        _delete_subvolume(snap_path)

    if orphan.snapshot_dir.exists():
        with contextlib.suppress(OSError):
            orphan.snapshot_dir.rmdir()

    if orphan.manifest_dir and orphan.manifest_dir.exists():
        shutil.rmtree(orphan.manifest_dir, ignore_errors=True)


def inspect_lane(project_id: str, lane_name: str) -> LaneInspection:
    """Inspect a Btrfs lane and enumerate what cleanup would delete."""
    _require_workspaces()
    lane_path = get_lanes_base_dir(project_id) / lane_name
    if not lane_path.exists():
        raise SnapshotError(f"Lane does not exist: {lane_path}")

    is_worktree = (lane_path / ".git").exists()
    branch = get_worktree_branch(lane_path) if is_worktree else None

    # Find snapshot subvolumes
    snap_base = get_workspace_snapshots_base_dir(project_id) / "lanes" / _sanitize_label(lane_name)
    snapshot_paths: list[Path] = []
    snapshot_dir: Path | None = None
    if snap_base.is_dir():
        snapshot_dir = snap_base
        snapshot_paths = sorted(p for p in snap_base.iterdir() if p.is_dir())

    # Find manifest/artifact dir
    scope = SnapshotScope("lane", lane_name, lane_path)
    manifest_base = Path.home() / ".local" / "share" / "st" / "snaps" / project_id / _scope_key(scope)
    manifest_dir = manifest_base if manifest_base.is_dir() else None

    return LaneInspection(
        project_id=project_id,
        lane_name=lane_name,
        lane_path=lane_path,
        is_git_worktree=is_worktree,
        branch=branch,
        snapshot_paths=snapshot_paths,
        snapshot_dir=snapshot_dir,
        manifest_dir=manifest_dir,
    )


def delete_lane(inspection: LaneInspection) -> None:
    """Delete a Btrfs lane, its snapshots, and metadata.

    Must be called from outside the lane directory (caller responsibility).
    """
    # 1. Remove git worktree registration first so failures stop before we
    # destroy any recoverable snapshot state.
    if inspection.is_git_worktree:
        git_file = inspection.lane_path / ".git"
        if not git_file.is_file():
            raise SnapshotError(
                f"Expected git worktree metadata at {git_file}, but it was missing."
            )

        content = git_file.read_text(encoding="utf-8").strip()
        if not content.startswith("gitdir:"):
            raise SnapshotError(
                f"Unexpected git worktree metadata format in {git_file}."
            )

        gitdir = Path(content.split(":", 1)[1].strip())
        common_dir = gitdir.parent.parent  # .git/worktrees → .git
        if common_dir.name != ".git":
            raise SnapshotError(
                f"Could not resolve canonical repo root for lane {inspection.lane_path}."
            )

        repo_root = common_dir.parent
        try:
            force_remove_worktree(inspection.lane_path, repo_root)
        except WorktreeError as exc:
            raise SnapshotError(f"Failed to remove git worktree registration: {exc}") from exc

        if inspection.branch and inspection.branch not in {"main", "master", "HEAD"}:
            branch_ref = f"refs/heads/{inspection.branch}"
            branch_result = run_git(["show-ref", "--verify", branch_ref], cwd=repo_root, check=False)
            if branch_result.returncode == 0:
                delete_result = run_git(
                    ["branch", "-D", inspection.branch],
                    cwd=repo_root,
                    check=False,
                )
                if delete_result.returncode != 0:
                    stderr = delete_result.stderr.strip() or delete_result.stdout.strip() or "unknown git error"
                    raise SnapshotError(
                        f"Failed to delete lane branch '{inspection.branch}': {stderr}"
                    )

    # 2. Delete snapshot subvolumes (read-only, must unset ro first)
    for snap_path in inspection.snapshot_paths:
        _delete_subvolume(snap_path)

    # 3. Remove empty snapshot directory
    if inspection.snapshot_dir and inspection.snapshot_dir.exists():
        with contextlib.suppress(OSError):
            inspection.snapshot_dir.rmdir()

    # 4. Delete the lane subvolume if git did not already remove it.
    _delete_subvolume(inspection.lane_path)

    # 5. Clean up manifest and artifacts
    if inspection.manifest_dir and inspection.manifest_dir.exists():
        shutil.rmtree(inspection.manifest_dir, ignore_errors=True)

    # 6. Remove any task checkpoint metadata that still points at this lane.
    with contextlib.suppress(Exception):
        from .checkpoint import remove_checkpoint_for_worktree_path

        remove_checkpoint_for_worktree_path(
            inspection.lane_path,
            project_id=inspection.project_id,
        )


# Public aliases for cross-module use (autosnapshot.py).
# Keep underscore originals for backward compat with tests that monkeypatch them.
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
    "SnapshotScope",
    "capture_snapshot",
    "delete_lane",
    "delete_orphaned_snapshots",
    "delete_subvolume",
    "find_orphaned_snapshot_dirs",
    "inspect_lane",
    "list_snapshots",
    "load_manifest",
    "recover_snapshot",
    "require_btrfs_subvolume",
    "require_workspaces",
    "resolve_scope",
    "restore_snapshot",
    "save_manifest",
]
