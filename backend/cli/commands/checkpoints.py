"""Checkpoints command for st CLI.

Shows active checkpoints from the canonical checkpoint metadata store.
Provides cleanup for stale metadata and orphaned branches.
"""

from __future__ import annotations

from typing import Annotated

import typer

from ..lib.checkpoint import SnapshotMeta, get_active_checkpoints, get_snapshot_info
from ..lib.checkpoint_branches import get_task_branches
from ..output import output_json
from ..output_context import OutputContext
from .checkpoints_cleanup import auto_cleanup_safe_items
from .checkpoints_formatters import (
    format_cleanup_summary,
    format_compact_checkpoints,
    format_details,
    format_review_needed,
)

app = typer.Typer(help="Checkpoint management - show active checkpoints, cleanup stale artifacts")


def _checkpoint_to_dict(cp: SnapshotMeta) -> dict:
    return {
        "task_id": cp.task_id,
        "project_id": cp.project_id,
        "task_branch": f"{cp.task_id}/main",
        "base_branch": cp.base_branch,
        "created_at": cp.created_at,
        "claimed_by": cp.claimed_by,
        "branches": get_task_branches(cp.task_id, project_id=cp.project_id),
    }


def _output_compact(ctx_obj: OutputContext, checkpoints: list, cleaned: tuple) -> None:
    cleaned_meta, cleaned_sql, cleaned_branches, needs_review = cleaned
    checkpoint_data = [info for cp in checkpoints if (info := get_snapshot_info(cp.task_id))]
    format_compact_checkpoints(checkpoint_data)
    format_cleanup_summary(cleaned_meta, cleaned_sql, cleaned_branches)
    format_review_needed(needs_review)


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
    if ctx.invoked_subcommand is not None:
        return
    if details:
        format_details(ctx.obj, details)
        return
    cleaned = auto_cleanup_safe_items(project)
    checkpoints = get_active_checkpoints(project)
    if ctx.obj.is_compact:
        _output_compact(ctx.obj, checkpoints, cleaned)
    else:
        output_json({"checkpoints": [_checkpoint_to_dict(cp) for cp in checkpoints], "total": len(checkpoints)})
