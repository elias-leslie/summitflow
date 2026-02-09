"""Task context command implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from ..client import APIError, STClient
from ..lib.worktree import get_worktree_info
from ..output import handle_api_error, output_context, output_subtask_context
from .tasks_helpers import fetch_phase_triggered_references, fetch_triggered_references


def get_task_context(
    task_id: str,
    subtask: str | None,
    client: STClient,
) -> None:
    """Get task or subtask context in a single call."""
    try:
        # Fetch task
        task = client.get_task(task_id)

        # Fetch task_spirit for normalized fields
        from app.storage.task_spirit import get_task_spirit

        spirit = get_task_spirit(task_id)
        if spirit:
            task["plan_status"] = spirit.get("plan_status", "draft")
            task["plan_approved_at"] = spirit.get("plan_approved_at")
            task["plan_approved_by"] = spirit.get("plan_approved_by")
            task["context"] = spirit.get("context")
            if spirit.get("objective"):
                task["objective"] = spirit["objective"]
            if spirit.get("spirit_anti"):
                task["spirit_anti"] = spirit["spirit_anti"]
            if spirit.get("decisions"):
                task["decisions"] = spirit["decisions"]
            if spirit.get("constraints"):
                task["constraints"] = spirit["constraints"]
            if spirit.get("done_when"):
                task["done_when"] = spirit["done_when"]
            if spirit.get("complexity"):
                task["complexity"] = spirit["complexity"]

        # Fetch subtasks with steps
        subtask_data = client.get_subtasks(task_id, include_steps=True)
        subtasks = subtask_data.get("subtasks", [])

        if subtask:
            # Subtask-scoped context
            from app.storage.subtask_dependencies import get_dependencies

            # Find the specific subtask
            target_subtask = None
            for st in subtasks:
                if st.get("subtask_id") == subtask:
                    target_subtask = st
                    break

            if not target_subtask:
                typer.echo(f"Error: Subtask {subtask} not found in task {task_id}", err=True)
                raise typer.Exit(1)

            # Get subtask dependencies with status
            deps = get_dependencies(target_subtask.get("id", ""))
            dep_status = []
            for dep_id in deps:
                for st in subtasks:
                    if st.get("id") == dep_id:
                        status = "DONE" if st.get("passes") else "PENDING"
                        dep_status.append({"subtask_id": st.get("subtask_id"), "status": status})
                        break

            # Fetch phase-triggered references
            phase = target_subtask.get("phase", "")
            phase_refs = fetch_phase_triggered_references(phase) if phase else []

            output_subtask_context(task, target_subtask, dep_status, phase_refs)
        else:
            # Full task context
            # Fetch blockers
            task_deps: list[dict[str, Any]] = client.list_dependencies(task_id)
            blockers: list[dict[str, Any]] = []
            for d in task_deps:
                if d.get("dependency_type") == "blocks" and d.get("depends_on_status") not in (
                    "completed",
                    "cancelled",
                ):
                    blocker_id = d.get("depends_on_task_id")
                    if blocker_id and isinstance(blocker_id, str):
                        try:
                            blocker_task = client.get_task(blocker_id)
                            blockers.append(blocker_task)
                        except APIError:
                            blockers.append({"id": blocker_id, "status": "unknown", "title": "?"})

            # Fetch task-type triggered references
            task_type = task.get("task_type", "")
            task_refs = fetch_triggered_references(task_type) if task_type else []

            output_context(task, subtasks, blockers, task_refs)

        # Show worktree info if available
        worktree_info = get_worktree_info(task_id)
        if worktree_info:
            worktree_path = str(worktree_info.path)
            home = str(Path.home())
            display_path = worktree_path.replace(home, "~")
            typer.echo("")
            typer.echo(f"WORKTREE: {display_path}")
            typer.echo(f"  branch: {worktree_info.branch}")
            typer.echo(f"  cd {display_path}  # to work in isolation")

    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None
