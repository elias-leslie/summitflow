"""Checkpoints command for st CLI.

Shows active checkpoints for visibility and debugging.
Provides cleanup for stale metadata and orphaned branches.
"""

from __future__ import annotations

from typing import Annotated

import typer

from ..lib.checkpoint import get_active_checkpoints, get_snapshot_info
from ..output import output_json
from ..output_context import OutputContext
from .checkpoints_branch_ops import get_task_branches
from .checkpoints_cleanup import auto_cleanup_safe_items
from .checkpoints_formatters import (
    format_cleanup_summary,
    format_compact_checkpoints,
    format_details,
    format_review_needed,
)

app = typer.Typer(help="Checkpoint management - show active checkpoints, cleanup stale artifacts")


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
        format_details(ctx.obj, details)
        return

    # Auto-cleanup stale items BEFORE listing (so stale items don't appear)
    cleaned_meta, cleaned_sql, cleaned_branches, needs_review = auto_cleanup_safe_items()

    # Now get active checkpoints (after cleanup)
    checkpoints = get_active_checkpoints(project)

    if ctx.obj.is_compact:
        checkpoint_data = []
        for cp in checkpoints:
            info = get_snapshot_info(cp.task_id)
            if info:
                checkpoint_data.append(info)
        format_compact_checkpoints(checkpoint_data)

        # Report what was cleaned
        format_cleanup_summary(cleaned_meta, cleaned_sql, cleaned_branches)

        # Report branches needing review with instructions
        format_review_needed(needs_review)
    else:
        output_json(
            {
                "checkpoints": [
                    {
                        "task_id": cp.task_id,
                        "project_id": cp.project_id,
                        "worktree_path": cp.worktree_path,
                        "base_branch": cp.base_branch,
                        "created_at": cp.created_at,
                        "claimed_by": cp.claimed_by,
                        "branches": get_task_branches(cp.task_id),
                    }
                    for cp in checkpoints
                ],
                "total": len(checkpoints),
            }
        )
