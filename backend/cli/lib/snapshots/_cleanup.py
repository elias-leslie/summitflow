"""Snapshot cleanup, residue detection, and lane inspection helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..worktree_ops import get_worktree_branch
from ..worktree_paths import (
    get_lanes_base_dir,
    get_workspace_snapshots_base_dir,
)
from ._helpers import _require_workspaces, _resolve_repo_root, _resolve_scope, _sanitize_label
from ._manifest import _load_manifest, _scope_key, _snapshot_manifest_root
from ._models import LaneInspection, SnapshotScope


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


def list_snapshots(*, project_id: str, cwd: str | Path | None = None):
    repo_root = _resolve_repo_root(cwd)
    scope = _resolve_scope(repo_root, project_id)
    return _load_manifest(project_id, scope)


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
        if not entry.is_dir() or (entry / ".git").exists():
            continue
        is_empty = not any(entry.iterdir())
        if is_empty:
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
        if not entry.is_dir() or entry.name in managed:
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
        lane_path = lanes_base / snap_dir.name
        if lane_path.exists():
            continue

        snapshot_paths = sorted(p for p in snap_dir.iterdir() if p.is_dir())
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


def inspect_lane(project_id: str, lane_name: str) -> LaneInspection:
    """Inspect a Btrfs lane and enumerate what cleanup would delete."""
    _require_workspaces()
    lane_path = get_lanes_base_dir(project_id) / lane_name
    if not lane_path.exists():
        from ._models import SnapshotError

        raise SnapshotError(f"Lane does not exist: {lane_path}")

    is_worktree = (lane_path / ".git").exists()
    branch = get_worktree_branch(lane_path) if is_worktree else None

    snap_base = get_workspace_snapshots_base_dir(project_id) / "lanes" / _sanitize_label(lane_name)
    snapshot_paths: list[Path] = []
    snapshot_dir: Path | None = None
    if snap_base.is_dir():
        snapshot_dir = snap_base
        snapshot_paths = sorted(p for p in snap_base.iterdir() if p.is_dir())

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
