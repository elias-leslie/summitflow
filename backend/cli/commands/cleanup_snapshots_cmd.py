"""Snapshot residue cleanup command body."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import typer

from ..lib.confirm_token import confirm_gate
from ..lib.quick_snapshots import delete_snapshot_residue, find_snapshot_residue
from ..lib.workspace_paths import workspaces_root_available
from ..output import output_error, output_success


def execute_snapshot_deletions(residues: list[Any]) -> tuple[int, list[str]]:
    """Delete snapshot residues; return (deleted_count, errors)."""
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


def run_snapshot_deletions(residues: list[Any], dry_run: bool) -> None:
    """Output dry-run preview or execute snapshot deletions and report results."""
    if dry_run:
        typer.echo("DRY RUN - would delete:")
        for residue in residues:
            typer.echo(f"  {residue.project_id or 'unowned'}/{residue.residue_name} ({residue.residue_type})")
        return

    cwd = Path.cwd()
    for residue in residues:
        try:
            cwd.relative_to(residue.path)
            os.chdir(Path.home())
            break
        except ValueError:
            continue

    deleted, errors = execute_snapshot_deletions(residues)
    for err in errors:
        typer.echo(f"  ERROR {err}", err=True)
    if errors:
        output_error(f"Deleted {deleted} target(s), {len(errors)} error(s)")
        raise typer.Exit(1)
    output_success(f"Deleted {deleted} target(s), 0 error(s)")


def cleanup_snapshots_command(
    residue_name: str | None,
    *,
    all_projects: bool,
    dry_run: bool,
    confirm: str | None,
    project_ids: list[str],
    current_project_id: str | None,
) -> None:
    """Delete legacy snapshot residue after confirm-token preview."""
    if not workspaces_root_available():
        output_error("Btrfs workspaces not available - nothing to clean up.")
        raise typer.Exit(1)

    residues = find_snapshot_residue(project_ids, project_id=current_project_id)
    if residue_name:
        residues = [residue for residue in residues if residue.residue_name == residue_name]
    _exit_if_empty(not residues, residue_name)

    scope_label = "all" if all_projects else (current_project_id or "unknown")
    command_key = f"cleanup-snapshots-{scope_label}-{residue_name or 'all-snapshots'}"
    preview_lines = [f"DELETE legacy snapshot residue: {len(residues)} target(s):", ""]
    for residue in residues:
        owner = residue.project_id or "unowned"
        preview_lines.extend([
            f"SNAPSHOT-RESIDUE {owner}/{residue.residue_name} [{residue.residue_type}]",
            f"  path: {residue.path}",
        ])
    cmd = " ".join(["st cleanup snapshots"] + ([residue_name] if residue_name else []) + (["--all"] if all_projects else []))
    confirm_gate(command_key, confirm, preview_lines, cmd)
    run_snapshot_deletions(residues, dry_run)


def _exit_if_empty(is_empty: bool, residue_name: str | None) -> None:
    if not is_empty:
        return
    if residue_name:
        output_error("No matching snapshot residue found to clean up.")
        raise typer.Exit(1)
    output_success("No legacy snapshot residue found to clean up.")
    raise typer.Exit(0)
