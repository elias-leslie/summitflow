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

app = typer.Typer(help="Checkpoint management - show active checkpoints, cleanup stale artifacts")


def _get_branch_unmerged_commits(branch: str) -> list[dict]:
    """Get unmerged commits for a branch (commits not in main)."""
    commits = []
    try:
        result = subprocess.run(
            ["git", "log", f"main..{branch}", "--oneline", "--format=%H|%s|%ar"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.strip().splitlines():
            if "|" in line:
                parts = line.split("|", 2)
                if len(parts) == 3:
                    commits.append({
                        "hash": parts[0][:8],
                        "message": parts[1],
                        "age": parts[2],
                    })
    except subprocess.CalledProcessError:
        pass
    return commits


def _auto_cleanup_safe_items() -> tuple[int, int, int, list[dict]]:
    """Auto-cleanup clearly safe items.

    Returns (stale_meta, legacy_sql, cleaned_branches, branches_needing_review).

    Branches needing review have unmerged commits and require judgment.
    """
    snapshots_dir = Path.cwd() / ".st" / "snapshots"
    cleaned_meta = 0
    cleaned_sql = 0
    cleaned_branches = 0
    branches_needing_review: list[dict] = []

    # Find and clean stale metadata (no worktree AND no branch)
    if snapshots_dir.exists():
        for meta_file in snapshots_dir.glob("*.meta.json"):
            try:
                import json

                meta = json.loads(meta_file.read_text())
                task_id = meta.get("task_id", "")
                project_id = meta.get("project_id")

                # Check if worktree or branch exists
                worktree = get_worktree_info(task_id, project_id)
                branches = _get_task_branches(task_id)

                if not worktree and not branches:
                    # Safe to delete - no worktree, no branch
                    meta_file.unlink()
                    cleaned_meta += 1
            except Exception:
                pass

        # Clean legacy SQL files
        for sql_file in snapshots_dir.glob("*.sql"):
            try:
                sql_file.unlink()
                cleaned_sql += 1
            except Exception:
                pass

    # Process orphaned branches - auto-delete only if 0 unmerged commits
    for branch in _get_orphaned_branches():
        commits = _get_branch_unmerged_commits(branch)

        if not commits:
            # 0 unmerged commits = safe to delete (already merged or identical to main)
            try:
                subprocess.run(
                    ["git", "branch", "-D", branch],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                cleaned_branches += 1
            except subprocess.CalledProcessError:
                pass
        else:
            # Has unmerged commits - needs review
            branches_needing_review.append({
                "branch": branch,
                "commits": commits,
            })

    return (cleaned_meta, cleaned_sql, cleaned_branches, branches_needing_review)


@app.callback(invoke_without_command=True)
def checkpoints_callback(
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
    """Show active checkpoints (default when no subcommand given)."""
    if ctx.obj is None:
        ctx.obj = OutputContext()

    # If a subcommand is invoked, don't run the default list behavior
    if ctx.invoked_subcommand is not None:
        return

    # Default behavior: list checkpoints (same as old checkpoints_command)
    if details:
        _format_details(ctx.obj, details)
        return

    # Auto-cleanup stale items BEFORE listing (so stale items don't appear)
    cleaned_meta, cleaned_sql, cleaned_branches, needs_review = _auto_cleanup_safe_items()

    # Now get active checkpoints (after cleanup)
    checkpoints = get_active_checkpoints(project)

    if ctx.obj.is_compact:
        checkpoint_data = []
        for cp in checkpoints:
            info = get_snapshot_info(cp.task_id)
            if info:
                checkpoint_data.append(info)
        _format_compact_checkpoints(checkpoint_data)

        # Report what was cleaned
        if cleaned_meta or cleaned_sql or cleaned_branches:
            parts = []
            if cleaned_meta:
                parts.append(f"{cleaned_meta} stale metadata")
            if cleaned_sql:
                parts.append(f"{cleaned_sql} legacy SQL")
            if cleaned_branches:
                parts.append(f"{cleaned_branches} orphaned branches")
            print(f"  (auto-cleaned: {', '.join(parts)})")

        # Report branches needing review with instructions
        if needs_review:
            print()
            print(f"ACTION REQUIRED - Branches with unmerged commits [{len(needs_review)}]:")
            for item in needs_review:
                branch = item["branch"]
                commits = item["commits"]
                print(f"  {branch} ({len(commits)} commit{'s' if len(commits) != 1 else ''}):")
                for commit in commits[:5]:  # Show max 5 commits
                    print(f"    - {commit['message']} ({commit['age']})")
                if len(commits) > 5:
                    print(f"    - ... and {len(commits) - 5} more")
            print()
            print("INSTRUCTIONS: Review each branch above:")
            print("  1. If commits are test artifacts or abandoned work → delete: git branch -D <branch>")
            print("  2. If commits appear to be valuable work → ask user before deleting")
            print("  3. If uncertain → ask user for guidance")
    else:
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


