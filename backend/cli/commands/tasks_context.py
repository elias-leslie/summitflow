"""Task context command implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from app.services.task_execution_readiness import assess_task_execution_readiness
from app.services.task_lane_preflight import check_task_lane_conflicts

from ..client import APIError, STClient
from ..lib.worktree import get_worktree_info
from ..output import handle_api_error, output_context, output_subtask_context
from .tasks_helpers import fetch_phase_triggered_references, fetch_triggered_references
from .tasks_progress import analyze_subtask_sync

_TERMINAL_TASK_STATUSES = {"completed", "cancelled", "abandoned", "failed", "blocked"}


def _enrich_task_from_spirit(task: dict[str, Any], task_id: str) -> None:
    """Enrich task dict with normalized fields from task_spirit storage."""
    from app.storage.task_spirit import get_task_spirit

    spirit = get_task_spirit(task_id)
    if not spirit:
        return

    task["plan_status"] = spirit.get("plan_status", "draft")
    task["plan_approved_at"] = spirit.get("plan_approved_at")
    task["plan_approved_by"] = spirit.get("plan_approved_by")
    task["context"] = spirit.get("context")

    optional_fields = ("objective", "spirit_anti", "decisions", "constraints", "done_when", "complexity")
    for field in optional_fields:
        if spirit.get(field):
            task[field] = spirit[field]


def _get_subtask_dep_status(
    target_subtask: dict[str, Any],
    subtasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return dependency status list for a subtask."""
    from app.storage.subtask_dependencies import get_dependencies

    deps = get_dependencies(target_subtask.get("id", ""))
    dep_status: list[dict[str, Any]] = []
    for dep_id in deps:
        for st in subtasks:
            if st.get("id") != dep_id:
                continue
            status = "DONE" if st.get("passes") else "PENDING"
            dep_status.append({"subtask_id": st.get("subtask_id"), "status": status})
            break
    return dep_status


def _get_blockers(
    task_id: str,
    task_deps: list[dict[str, Any]],
    client: STClient,
) -> list[dict[str, Any]]:
    """Fetch blocker tasks for the given task dependencies."""
    active_dep_types = {"completed", "cancelled"}
    blockers: list[dict[str, Any]] = []
    for d in task_deps:
        if d.get("dependency_type") != "blocks":
            continue
        if d.get("depends_on_status") in active_dep_types:
            continue
        blocker_id = d.get("depends_on_task_id")
        if not blocker_id or not isinstance(blocker_id, str):
            continue
        try:
            blockers.append(client.get_task(blocker_id))
        except APIError:
            blockers.append({"id": blocker_id, "status": "unknown", "title": "?"})
    return blockers


def _display_worktree_info(task_id: str) -> None:
    """Print worktree path and branch if a worktree exists for this task."""
    worktree_info = get_worktree_info(task_id)
    if not worktree_info:
        return
    worktree_path = str(worktree_info.path)
    home = str(Path.home())
    display_path = worktree_path.replace(home, "~")
    typer.echo("")
    typer.echo(f"WORKTREE: {display_path}")
    typer.echo(f"  branch: {worktree_info.branch}")
    typer.echo(f"  cd {display_path}  # to work in isolation")


def _handle_subtask_context(
    task: dict[str, Any],
    subtask: str,
    subtasks: list[dict[str, Any]],
) -> None:
    """Output context scoped to a specific subtask."""
    target_subtask = next(
        (st for st in subtasks if st.get("subtask_id") == subtask),
        None,
    )
    if not target_subtask:
        typer.echo(f"Error: Subtask {subtask} not found in task {task.get('id', '')}", err=True)
        raise typer.Exit(1)

    dep_status = _get_subtask_dep_status(target_subtask, subtasks)
    phase = target_subtask.get("phase", "")
    phase_refs = fetch_phase_triggered_references(phase) if phase else []
    output_subtask_context(task, target_subtask, dep_status, phase_refs)


def _handle_task_context(
    task: dict[str, Any],
    task_id: str,
    subtasks: list[dict[str, Any]],
    client: STClient,
) -> None:
    """Output full task context including blockers and references."""
    task_deps: list[dict[str, Any]] = client.list_dependencies(task_id)
    blockers = _get_blockers(task_id, task_deps, client)
    task_type = task.get("task_type", "")
    task_refs = fetch_triggered_references(task_type) if task_type else []
    task["execution_readiness"] = assess_task_execution_readiness(task, task, subtasks)
    task["completion_readiness"] = client.get_task_completion_readiness(task_id)
    if task.get("status") not in _TERMINAL_TASK_STATUSES:
        task["lane_preflight"] = check_task_lane_conflicts(task_id, task["project_id"]).to_dict()
    sync_analysis = analyze_subtask_sync(subtasks)
    task["syncable_subtasks"] = sync_analysis.syncable
    task["syncable_subtasks_skipped"] = sync_analysis.skipped
    output_context(task, subtasks, blockers, task_refs)


def get_task_context(
    task_id: str,
    subtask: str | None,
    client: STClient,
) -> None:
    """Get task or subtask context in a single call."""
    try:
        task = client.get_task(task_id)
        task_id = str(task.get("id", task_id))
        _enrich_task_from_spirit(task, task_id)

        subtask_data = client.get_subtasks(task_id, include_steps=True)
        subtasks = subtask_data.get("subtasks", [])

        if subtask:
            _handle_subtask_context(task, subtask, subtasks)
        else:
            _handle_task_context(task, task_id, subtasks, client)

        _display_worktree_info(task_id)

    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None
