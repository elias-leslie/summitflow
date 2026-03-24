"""Formatting functions for checkpoints command.

Handles output formatting for compact and detailed checkpoint displays.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..lib.checkpoint import get_snapshot_info
from ..lib.checkpoint_branches import get_task_branches
from ..output import output_json
from ..output_context import OutputContext


def format_age(created_at: str) -> str:
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


def _format_subtask_branches(branches: list[dict[str, Any]]) -> None:
    """Print subtask branch lines indented under a checkpoint entry."""
    for br in branches:
        if br["type"] == "subtask":
            subtask_id = br["subtask_id"]
            branch_name = br["branch"]
            print(f"  └─ {subtask_id} {branch_name}")


def _format_checkpoint_line(cp: dict[str, Any]) -> None:
    """Print a single checkpoint summary line and its subtask branches."""
    task_id = cp.get("task_id", "?")
    age = format_age(cp.get("created_at", ""))
    size = cp.get("size", "?")
    project_id = cp.get("project_id")

    branches = get_task_branches(task_id, project_id=project_id)
    branch_count = len(branches)

    print(f"{task_id}|{age}|{branch_count} branches|{size}")
    _format_subtask_branches(branches)


def format_compact_checkpoints(checkpoints: list[dict[str, Any]]) -> None:
    """Output checkpoints in TOON format."""
    if not checkpoints:
        print("CHECKPOINTS[0]")
        return

    # Group by project
    by_project: dict[str, list[dict[str, Any]]] = {}
    for cp in checkpoints:
        proj = cp.get("project_id", "unknown")
        if proj not in by_project:
            by_project[proj] = []
        by_project[proj].append(cp)

    total = len(checkpoints)
    print(f"CHECKPOINTS[{total}]")

    for _project_id, project_checkpoints in by_project.items():
        for cp in project_checkpoints:
            _format_checkpoint_line(cp)


def format_details(out: OutputContext, task_id: str) -> None:
    """Show detailed checkpoint info for a specific task."""
    info = get_snapshot_info(task_id)
    if not info:
        print(f"No checkpoint found for {task_id}")
        return

    age = format_age(str(info.get("created_at", "")))
    branches = get_task_branches(task_id, project_id=info.get("project_id"))

    if out.is_compact:
        print(f"CHECKPOINT:{task_id}")
        print(f"  Project: {info.get('project_id', '?')}")
        print(f"  Worktree: {info.get('worktree_path', '?')}")
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


def format_cleanup_summary(cleaned_meta: int, cleaned_sql: int, cleaned_branches: int) -> None:
    """Format and print cleanup summary if items were cleaned."""
    if cleaned_meta or cleaned_sql or cleaned_branches:
        parts = []
        if cleaned_meta:
            parts.append(f"{cleaned_meta} stale metadata")
        if cleaned_sql:
            parts.append(f"{cleaned_sql} legacy SQL")
        if cleaned_branches:
            parts.append(f"{cleaned_branches} orphaned branches")
        print(f"  (auto-cleaned: {', '.join(parts)})")


def _format_review_item(item: dict[str, Any]) -> None:
    """Print a single review item with its commits."""
    branch = item["branch"]
    commits = item["commits"]
    print(f"  {branch} ({len(commits)} commit{'s' if len(commits) != 1 else ''}):")
    for commit in commits[:5]:  # Show max 5 commits
        print(f"    - {commit['message']} ({commit['age']})")
    if len(commits) > 5:
        print(f"    - ... and {len(commits) - 5} more")


def format_review_needed(needs_review: list[dict[str, Any]]) -> None:
    """Format and print branches needing review with instructions."""
    if not needs_review:
        return

    print()
    print(f"ACTION REQUIRED - Branches with unmerged commits [{len(needs_review)}]:")
    for item in needs_review:
        _format_review_item(item)
    print()
    print("INSTRUCTIONS: Review each branch above:")
    print(
        "  1. If commits are test artifacts or abandoned work → delete: git branch -D <branch>"
    )
    print("  2. If commits appear to be valuable work → ask user before deleting")
    print("  3. If uncertain → ask user for guidance")
