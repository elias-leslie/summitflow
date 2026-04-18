"""Snapshot cleanup and project-scope residue detection helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..workspace_paths import get_workspace_snapshots_base_dir
from ._helpers import _require_workspaces, _resolve_repo_root, _resolve_scope
from ._manifest import _load_manifest, _snapshot_manifest_root


@dataclass(frozen=True)
class SnapshotResidue:
    """Legacy snapshot state that falls outside the managed project layout."""

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
        residues.extend(find_legacy_manifest_dirs(pid))

    return sorted(
        residues,
        key=lambda residue: (
            residue.project_id or "",
            residue.residue_type,
            residue.residue_name,
        ),
    )
