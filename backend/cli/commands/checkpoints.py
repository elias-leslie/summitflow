"""Checkpoints command for st CLI.

Shows active checkpoints for visibility and debugging.
Provides cleanup for stale metadata and orphaned branches.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from ..lib.checkpoint import get_active_checkpoints, get_snapshot_info
from ..lib.worktree import get_worktree_info
from ..output import output_json
from ..output_context import OutputContext

app = typer.Typer(help="Show active checkpoints")


@app.callback()
def checkpoints_callback(ctx: typer.Context) -> None:
    """Initialize context if not set by parent app."""
    if ctx.obj is None:
        ctx.obj = OutputContext()


def _get_task_branches(task_id: str) -> list[dict[str, str]]:
    """Get all branches for a task (task branch + subtask branches)."""
    branches = []
    try:
        result = subprocess.run(
            ["git", "branch", "--list", f"{task_id}/*"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.splitlines():
            branch = line.strip().lstrip("* ")
            if branch:
                # Determine if it's a subtask or task branch
                # Task branch ends with /main, subtask branches end with /X.Y
                suffix = branch.split("/")[-1] if "/" in branch else ""
                if suffix == "main":
                    branches.append({"branch": branch, "subtask_id": "", "type": "task"})
                else:
                    branches.append({"branch": branch, "subtask_id": suffix, "type": "subtask"})
    except subprocess.CalledProcessError:
        pass
    return branches


def _format_age(created_at: str) -> str:
    """Format age from ISO timestamp to human-readable string."""
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        age = datetime.now(UTC) - created
        hours = int(age.total_seconds() / 3600)
        mins = int((age.total_seconds() % 3600) / 60)

        if hours >= 24:
            days = hours // 24
            return f"{days}d ago"
        elif hours > 0:
            return f"{hours}h ago"
        else:
            return f"{mins}m ago"
    except (ValueError, TypeError):
        return "unknown"


def _format_compact_checkpoints(checkpoints: list[dict]) -> None:
    """Output checkpoints in TOON format."""
    if not checkpoints:
        print("CHECKPOINTS[0]")
        return

    # Group by project
    by_project: dict[str, list[dict]] = {}
    for cp in checkpoints:
        proj = cp.get("project_id", "unknown")
        if proj not in by_project:
            by_project[proj] = []
        by_project[proj].append(cp)

    total = len(checkpoints)
    print(f"CHECKPOINTS[{total}]")

    for _project_id, project_checkpoints in by_project.items():
        for cp in project_checkpoints:
            task_id = cp.get("task_id", "?")
            age = _format_age(cp.get("created_at", ""))
            size = cp.get("size", "?")

            # Get branches for this task
            branches = _get_task_branches(task_id)
            branch_count = len(branches)

            print(f"{task_id}|{age}|{branch_count} branches|{size}")

            # Show subtask branches indented
            for br in branches:
                if br["type"] == "subtask":
                    subtask_id = br["subtask_id"]
                    branch_name = br["branch"]
                    print(f"  └─ {subtask_id} {branch_name}")


def _format_details(out: OutputContext, task_id: str) -> None:
    """Show detailed checkpoint info for a specific task."""
    info = get_snapshot_info(task_id)
    if not info:
        print(f"No checkpoint found for {task_id}")
        return

    age = _format_age(info.get("created_at", ""))
    branches = _get_task_branches(task_id)

    if out.is_compact:
        print(f"CHECKPOINT:{task_id}")
        print(f"  Project: {info.get('project_id', '?')}")
        print(f"  Snapshot: {info.get('snapshot_path', '?')} ({info.get('size', '?')})")
        print(f"  Base branch: {info.get('base_branch', '?')}")
        print(f"  Created: {info.get('created_at', '?')} ({age})")
        print(f"  Claimed by: {info.get('claimed_by', '?')}")
        print()
        if branches:
            print(f"BRANCHES[{len(branches)}]")
            for br in branches:
                btype = br["type"]
                branch = br["branch"]
                print(f"  {branch} [{btype}]")
    else:
        output_json(
            {
                "task_id": task_id,
                "checkpoint": info,
                "branches": branches,
            }
        )


@app.command(name="checkpoints")
def checkpoints_command(
    ctx: typer.Context,
    project: Annotated[
        str | None,
        typer.Option("--project", "-p", help="Filter by project ID"),
    ] = None,
    details: Annotated[
        str | None,
        typer.Option("--details", "-d", help="Show details for specific task"),
    ] = None,
) -> None:
    """Show active checkpoints.

    Lists all active task checkpoints with their subtask branches.
    Use --details to see full metadata for a specific task.

    Examples:
        st checkpoints                      # List all active checkpoints
        st checkpoints --project summitflow # Filter by project
        st checkpoints --details task-abc   # Show full details
    """
    if details:
        _format_details(ctx.obj, details)
        return

    # Get all checkpoints
    checkpoints = get_active_checkpoints(project)

    if ctx.obj.is_compact:
        # Build checkpoint data with extra info
        checkpoint_data = []
        for cp in checkpoints:
            info = get_snapshot_info(cp.task_id)
            if info:
                checkpoint_data.append(info)

        _format_compact_checkpoints(checkpoint_data)
    else:
        # JSON output
        output_json(
            {
                "checkpoints": [
                    {
                        "task_id": cp.task_id,
                        "project_id": cp.project_id,
                        "snapshot_path": cp.snapshot_path,
                        "base_branch": cp.base_branch,
                        "created_at": cp.created_at,
                        "claimed_by": cp.claimed_by,
                        "branches": _get_task_branches(cp.task_id),
                    }
                    for cp in checkpoints
                ],
                "total": len(checkpoints),
            }
        )


def _get_orphaned_branches() -> list[str]:
    """Find task branches without corresponding metadata."""
    orphaned = []
    try:
        result = subprocess.run(
            ["git", "branch", "--list", "task-*/*"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.splitlines():
            branch = line.strip().lstrip("*+ ")
            if not branch:
                continue
            # Extract task_id from branch name (e.g., "task-abc123/main" -> "task-abc123")
            task_id = branch.split("/")[0] if "/" in branch else branch
            # Check if metadata exists for this task
            info = get_snapshot_info(task_id)
            if not info:
                orphaned.append(branch)
    except subprocess.CalledProcessError:
        pass
    return orphaned


def _get_legacy_sql_files() -> list[Path]:
    """Find legacy .sql snapshot files."""
    snapshots_dir = Path.cwd() / ".st" / "snapshots"
    if not snapshots_dir.exists():
        return []
    return list(snapshots_dir.glob("*.sql"))


def _analyze_checkpoint_status(checkpoints: list) -> dict:
    """Analyze checkpoint status: active, stale, or orphaned.

    Returns dict with:
        - active: checkpoints with valid worktrees
        - stale: metadata without worktree or branch
        - orphaned_branches: branches without metadata
        - legacy_files: old .sql files
    """
    active = []
    stale = []

    for cp in checkpoints:
        task_id = cp.task_id
        project_id = cp.project_id

        # Check if worktree exists
        worktree = get_worktree_info(task_id, project_id)
        branches = _get_task_branches(task_id)

        if worktree or branches:
            active.append({"checkpoint": cp, "has_worktree": bool(worktree), "branches": branches})
        else:
            stale.append(cp)

    return {
        "active": active,
        "stale": stale,
        "orphaned_branches": _get_orphaned_branches(),
        "legacy_files": _get_legacy_sql_files(),
    }


@app.command(name="cleanup")
def cleanup_command(
    ctx: typer.Context,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Actually delete (default is dry-run)"),
    ] = False,
    branches: Annotated[
        bool,
        typer.Option("--branches", "-b", help="Also clean orphaned branches"),
    ] = False,
) -> None:
    """Clean up stale checkpoints and orphaned artifacts.

    By default runs in dry-run mode showing what would be removed.
    Use --force to actually delete.

    Cleans:
    - Stale metadata: .meta.json without worktree or branch
    - Legacy SQL files: old .sql snapshots from pre-worktree era
    - Orphaned branches: task-*/main branches without metadata (with --branches)

    Examples:
        st checkpoints cleanup              # Dry-run, show what would be removed
        st checkpoints cleanup --force      # Actually remove stale items
        st checkpoints cleanup --branches   # Include orphaned branches in cleanup
    """
    checkpoints = get_active_checkpoints()
    analysis = _analyze_checkpoint_status(checkpoints)

    stale = analysis["stale"]
    legacy = analysis["legacy_files"]
    orphaned = analysis["orphaned_branches"] if branches else []

    total_issues = len(stale) + len(legacy) + len(orphaned)

    if total_issues == 0:
        print("CLEANUP: No issues found")
        print(f"  Active checkpoints: {len(analysis['active'])}")
        if not branches:
            orphan_count = len(analysis["orphaned_branches"])
            if orphan_count > 0:
                print(f"  Orphaned branches: {orphan_count} (use --branches to clean)")
        return

    mode = "REMOVING" if force else "DRY-RUN (use --force to delete)"
    print(f"CLEANUP: {mode}")
    print()

    removed_meta = 0
    removed_sql = 0
    removed_branches = 0

    # Stale metadata
    if stale:
        print(f"Stale metadata [{len(stale)}]:")
        for cp in stale:
            meta_path = Path.cwd() / ".st" / "snapshots" / f"{cp.task_id}.meta.json"
            age = _format_age(cp.created_at)
            print(f"  {cp.task_id} ({age}) - no worktree/branch")
            if force and meta_path.exists():
                meta_path.unlink()
                removed_meta += 1
        print()

    # Legacy SQL files
    if legacy:
        print(f"Legacy SQL files [{len(legacy)}]:")
        for sql_file in legacy:
            size_kb = sql_file.stat().st_size // 1024
            print(f"  {sql_file.name} ({size_kb}KB)")
            if force:
                sql_file.unlink()
                removed_sql += 1
        print()

    # Orphaned branches
    if orphaned:
        print(f"Orphaned branches [{len(orphaned)}]:")
        for branch in orphaned:
            print(f"  {branch}")
            if force:
                try:
                    subprocess.run(
                        ["git", "branch", "-D", branch],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    removed_branches += 1
                except subprocess.CalledProcessError as e:
                    print(f"    Failed to delete: {e.stderr.strip()}")
        print()

    if force:
        print(f"Removed: {removed_meta} metadata, {removed_sql} SQL files, {removed_branches} branches")
    else:
        print(f"Would remove: {len(stale)} metadata, {len(legacy)} SQL files, {len(orphaned)} branches")
