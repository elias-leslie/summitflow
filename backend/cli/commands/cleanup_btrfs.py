"""Btrfs lane and snapshot cleanup helpers."""

from __future__ import annotations

import os
from pathlib import Path

import typer

from ..lib.checkpoint import get_stale_checkpoints


def collect_lane_inspections(project_ids: list[str], lane_name: str | None) -> list:
    """Enumerate and inspect lanes for each project."""
    from ..lib.quick_snapshots import SnapshotError, inspect_lane
    from ..lib.worktree_paths import get_lanes_base_dir

    inspections = []
    for pid in project_ids:
        lanes_base = get_lanes_base_dir(pid)
        if not lanes_base.is_dir():
            continue
        names = [lane_name] if lane_name else sorted(d.name for d in lanes_base.iterdir() if d.is_dir())
        for name in names:
            try:
                inspections.append(inspect_lane(pid, name))
            except SnapshotError:
                continue
    return inspections


def collect_orphaned_snap_dirs(project_ids: list[str], lane_name: str | None) -> list:
    """Find orphaned snapshot directories (skipped when targeting a specific lane)."""
    if lane_name:
        return []
    from ..lib.quick_snapshots import find_orphaned_snapshot_dirs

    orphaned = []
    for pid in project_ids:
        orphaned.extend(find_orphaned_snapshot_dirs(pid))
    return orphaned


def collect_stale_checkpoints_for_lanes(project_ids: list[str], lane_name: str | None) -> list:
    """Collect stale checkpoints, optionally filtered by lane name."""
    stale = []
    for pid in project_ids:
        for cp in get_stale_checkpoints(pid):
            cp_lane = Path(cp.worktree_path).name if cp.worktree_path else None
            if lane_name and cp.task_id != lane_name and cp_lane != lane_name:
                continue
            stale.append(cp)
    return stale


def escape_cwd(candidate_paths: list[Path]) -> None:
    """If cwd is inside any candidate path, cd to home before deletion."""
    cwd = Path.cwd()
    for p in candidate_paths:
        try:
            cwd.relative_to(p)
            os.chdir(Path.home())
            return
        except ValueError:
            pass


def build_lane_preview_lines(
    inspections: list, orphaned_snap_dirs: list, stale_checkpoints: list, lane_name: str | None
) -> list[str]:
    """Build the confirm-gate preview lines for lane cleanup."""
    lines: list[str] = []
    for insp in inspections:
        wt_label = "git-worktree" if insp.is_git_worktree else "orphan"
        lines.append(f"LANE {insp.project_id}/{insp.lane_name} [{wt_label}]")
        lines.append(f"  subvolume: {insp.lane_path}")
        if insp.branch:
            lines.append(f"  branch:   {insp.branch}")
        lines.append(f"  snapshots: {len(insp.snapshot_paths)}")
        for sp in insp.snapshot_paths:
            lines.append(f"    {sp.name}")
        if insp.manifest_dir:
            lines.append(f"  manifest:  {insp.manifest_dir}")
    for orphan in orphaned_snap_dirs:
        lines.append(f"ORPHAN-SNAPSHOTS {orphan.project_id}/{orphan.lane_name} [lane-deleted]")
        lines.append(f"  snapshot-dir: {orphan.snapshot_dir}")
        lines.append(f"  snapshots: {len(orphan.snapshot_paths)}")
        for sp in orphan.snapshot_paths:
            lines.append(f"    {sp.name}")
        if orphan.manifest_dir:
            lines.append(f"  manifest:  {orphan.manifest_dir}")
    for cp in stale_checkpoints:
        lines.append(f"STALE-CHECKPOINT {cp.project_id}/{cp.task_id}")
        lines.append(f"  worktree: {cp.worktree_path or '-'}")
        lines.append(f"  created:  {cp.created_at}")
    total_subvols = (
        sum(i.total_items for i in inspections)
        + sum(o.total_items for o in orphaned_snap_dirs)
    )
    total_targets = len(inspections) + len(orphaned_snap_dirs) + len(stale_checkpoints)
    summary = "DELETE explicit lane target(s)" if lane_name else "DELETE orphaned target(s)"
    lines.insert(0, f"{summary}: {total_targets} target(s), {total_subvols} subvolume(s):")
    lines.insert(1, "")
    return lines


def execute_lane_deletions(inspections: list, orphaned_snap_dirs: list, stale_checkpoints: list) -> tuple[int, list[str]]:
    """Delete all lane targets; return (deleted_count, errors)."""
    from ..lib.checkpoint import remove_snapshot
    from ..lib.quick_snapshots import delete_lane, delete_orphaned_snapshots

    deleted = 0
    errors: list[str] = []
    for insp in inspections:
        try:
            delete_lane(insp)
            typer.echo(f"  Deleted lane: {insp.project_id}/{insp.lane_name}")
            deleted += 1
        except Exception as exc:
            errors.append(f"{insp.project_id}/{insp.lane_name}: {exc}")
    for orphan in orphaned_snap_dirs:
        try:
            delete_orphaned_snapshots(orphan)
            typer.echo(f"  Deleted orphaned snapshots: {orphan.project_id}/{orphan.lane_name}")
            deleted += 1
        except Exception as exc:
            errors.append(f"orphan:{orphan.project_id}/{orphan.lane_name}: {exc}")
    for cp in stale_checkpoints:
        try:
            remove_snapshot(cp.task_id, remove_worktree=False, project_id=cp.project_id)
            typer.echo(f"  Deleted stale checkpoint: {cp.project_id}/{cp.task_id}")
            deleted += 1
        except Exception as exc:
            errors.append(f"checkpoint:{cp.project_id}/{cp.task_id}: {exc}")
    return deleted, errors


def execute_snapshot_deletions(residues: list) -> tuple[int, list[str]]:
    """Delete snapshot residues; return (deleted_count, errors)."""
    from ..lib.quick_snapshots import delete_snapshot_residue

    deleted = 0
    errors: list[str] = []
    for residue in residues:
        label = f"{residue.project_id or 'unowned'}/{residue.residue_name}"
        try:
            delete_snapshot_residue(residue)
            typer.echo(f"  Deleted snapshot residue: {label}")
            deleted += 1
        except Exception as exc:
            errors.append(f"{label}: {exc}")
    return deleted, errors
