"""Checkpoints command for st CLI.

Shows active checkpoints for visibility and debugging.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import Annotated

import typer

from ..lib.checkpoint import get_active_checkpoints, get_snapshot_info
from ..output import is_compact, output_json

app = typer.Typer(help="Show active checkpoints")


def _get_task_branches(task_id: str) -> list[dict[str, str]]:
    """Get all branches for a task (task branch + subtask branches)."""
    branches = []
    try:
        result = subprocess.run(
            ["git", "branch", "--list", f"{task_id}*"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.splitlines():
            branch = line.strip().lstrip("* ")
            if branch:
                # Determine if it's a subtask branch
                if "/" in branch:
                    parts = branch.split("/")
                    subtask_id = parts[-1] if len(parts) > 1 else ""
                    branches.append({"branch": branch, "subtask_id": subtask_id, "type": "subtask"})
                else:
                    branches.append({"branch": branch, "subtask_id": "", "type": "task"})
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

    for project_id, project_checkpoints in by_project.items():
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


def _format_details(task_id: str) -> None:
    """Show detailed checkpoint info for a specific task."""
    info = get_snapshot_info(task_id)
    if not info:
        print(f"No checkpoint found for {task_id}")
        return

    age = _format_age(info.get("created_at", ""))
    branches = _get_task_branches(task_id)

    if is_compact():
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
        output_json({
            "task_id": task_id,
            "checkpoint": info,
            "branches": branches,
        })


@app.command(name="checkpoints")
def checkpoints_command(
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
        _format_details(details)
        return

    # Get all checkpoints
    checkpoints = get_active_checkpoints(project)

    if is_compact():
        # Build checkpoint data with extra info
        checkpoint_data = []
        for cp in checkpoints:
            info = get_snapshot_info(cp.task_id)
            if info:
                checkpoint_data.append(info)

        _format_compact_checkpoints(checkpoint_data)
    else:
        # JSON output
        output_json({
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
        })
