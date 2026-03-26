"""Btrfs lane and snapshot cleanup helpers."""

from __future__ import annotations

import os
from pathlib import Path

import typer

from ..lib.checkpoint import get_stale_checkpoints
from ..lib.worktree_paths import get_workspaces_root
from ..output import output_error, output_success


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


def exit_if_empty(is_empty: bool, named: str | None, msg_named: str, msg_all: str) -> None:
    """Output result for empty target collection and raise Exit."""
    if not is_empty:
        return
    if named:
        output_error(msg_named)
        raise typer.Exit(1)
    output_success(msg_all)
    raise typer.Exit(0)


def resolve_lanes_project_ids(all_projects: bool, project_id: str | None) -> list[str]:
    """Resolve the list of project IDs to scan for lane cleanup."""
    if all_projects:
        lanes_root = get_workspaces_root() / "lanes"
        return sorted(d.name for d in lanes_root.iterdir() if d.is_dir()) if lanes_root.is_dir() else []
    return [project_id]  # type: ignore[list-item]


def collect_lane_targets(project_ids: list[str], lane_name: str | None):
    """Collect lane inspections, orphaned snap dirs, and stale checkpoints."""
    all_inspections = collect_lane_inspections(project_ids, lane_name)
    inspections = all_inspections if lane_name else [i for i in all_inspections if not i.is_git_worktree]
    return (
        inspections,
        collect_orphaned_snap_dirs(project_ids, lane_name),
        collect_stale_checkpoints_for_lanes(project_ids, lane_name),
    )


def run_lane_deletions(inspections, orphaned_snap_dirs, stale_checkpoints, dry_run: bool) -> None:
    """Output dry-run preview or execute lane deletions and report results."""
    if dry_run:
        typer.echo("DRY RUN — would delete:")
        for insp in inspections:
            typer.echo(f"  {insp.project_id}/{insp.lane_name} ({insp.total_items} subvolumes)")
        for orphan in orphaned_snap_dirs:
            typer.echo(f"  {orphan.project_id}/{orphan.lane_name} orphaned snapshots ({orphan.total_items})")
        for cp in stale_checkpoints:
            typer.echo(f"  {cp.project_id}/{cp.task_id} stale checkpoint metadata")
        return
    escape_cwd([insp.lane_path for insp in inspections])
    deleted, errors = execute_lane_deletions(inspections, orphaned_snap_dirs, stale_checkpoints)
    output_success(f"Deleted {deleted} target(s), {len(errors)} error(s)")
    for err in errors:
        typer.echo(f"  ERROR {err}", err=True)


def run_snapshot_deletions(residues, dry_run: bool) -> None:
    """Output dry-run preview or execute snapshot deletions and report results."""
    if dry_run:
        typer.echo("DRY RUN — would delete:")
        for residue in residues:
            typer.echo(f"  {residue.project_id or 'unowned'}/{residue.residue_name} ({residue.residue_type})")
        return
    escape_cwd([residue.path for residue in residues])
    deleted, errors = execute_snapshot_deletions(residues)
    output_success(f"Deleted {deleted} target(s), {len(errors)} error(s)")
    for err in errors:
        typer.echo(f"  ERROR {err}", err=True)


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
