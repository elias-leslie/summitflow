"""Task creation command implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_error, output_task
from .tasks_import import create_from_file, import_plan_file


def _build_task_data(
    title: str,
    task_type: str,
    priority: int,
    description: str | None,
    labels: str | None,
    parent: str | None,
    autonomous: bool,
) -> dict[str, Any]:
    data: dict[str, Any] = {"title": title, "task_type": task_type, "priority": priority}
    if description:
        data["description"] = description
    if labels:
        data["labels"] = labels.split(",")
    if parent:
        data["parent_task_id"] = parent
    if autonomous:
        data["autonomous"] = True
    return data


def _apply_blocked_by(
    client: STClient, task: dict[str, Any], blocked_by: str
) -> dict[str, Any]:
    try:
        client.add_dependency(task["id"], blocked_by, dep_type="blocks")
        task["blocked_by"] = blocked_by
    except APIError as e:
        task["dependency_error"] = e.detail
    return task


def create_task_command(
    title: str | None,
    from_file: Path | None,
    dry_run: bool,
    description: str | None,
    priority: int,
    labels: str | None,
    task_type: str,
    parent: str | None,
    plan: Path | None,
    blocked_by: str | None,
    autonomous: bool,
    task_id: str | None = None,
) -> None:
    """Create a new task or batch create from file.

    Examples:
        st create "Fix bug" -t bug -p 2 -l "complexity:small,domains:backend"
        st create "Add feature" -t feature -p 1 --parent task-abc123
        st create "Implement X" --blocked-by task-abc123
        st create "AutoTest" --autonomous  # Enable autonomous execution
        st create --from-file tasks.json
        st create --from-file tasks.json --dry-run
        st create --plan plan.json  # Import plan as task
        st create --plan plan.json --task existing-id  # Update existing task
    """
    if plan:
        client = STClient()
        task, tid = import_plan_file(plan, dry_run, task_id, client)
        if not dry_run:
            complexity = task.get("complexity", "SIMPLE")
            subtask_count = len(task.get("subtasks") or [])
            suffix = "intent-only" if subtask_count == 0 else f"{subtask_count} subtasks"
            typer.echo(f"IMPORT:{tid}|{complexity}|{suffix}")
        return

    if from_file:
        create_from_file(from_file, dry_run)
        return

    if not title:
        output_error("Either provide a title or use --from-file / --plan")
        raise typer.Exit(1)

    if dry_run:
        output_error("--dry-run only works with --from-file or --plan")
        raise typer.Exit(1)

    client = STClient()
    data = _build_task_data(title, task_type, priority, description, labels, parent, autonomous)

    try:
        task = client.create_task(data)
    except APIError as e:
        handle_api_error(e)
        return

    if blocked_by:
        task = _apply_blocked_by(client, task, blocked_by)

    output_task(task)
