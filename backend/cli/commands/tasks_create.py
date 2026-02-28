"""Task creation command implementation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_error, output_task
from .tasks_import import create_from_file


def _build_task_data(
    title: str,
    task_type: str,
    priority: int,
    description: str | None,
    labels: str | None,
    parent: str | None,
    autonomous: bool,
    objective: str | None = None,
    spirit_anti: str | None = None,
    done_when: list[str] | None = None,
    complexity: str | None = None,
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
    if objective:
        data["objective"] = objective
    if spirit_anti:
        data["spirit_anti"] = spirit_anti
    if done_when:
        data["done_when"] = done_when
    if complexity:
        data["complexity"] = complexity
    return data


def _apply_plan(client: STClient, task: dict[str, Any], plan: str) -> dict[str, Any]:
    try:
        plan_content = json.loads(plan)
        task = client.update_task(task["id"], plan_content=plan_content)
    except (json.JSONDecodeError, APIError) as e:
        output_error(f"Failed to set plan: {e}")
    return task


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
    plan: str | None,
    blocked_by: str | None,
    autonomous: bool,
    *,
    objective: str | None = None,
    spirit_anti: str | None = None,
    done_when: list[str] | None = None,
    complexity: str | None = None,
) -> None:
    """Create a new task, import from plan file, or batch create from file.

    Examples:
        st create "Fix bug" -t bug -p 2 -l "complexity:small,domains:backend"
        st create "Add feature" -t feature -p 1 --parent task-abc123
        st create "Implement X" --blocked-by task-abc123
        st create "Fix X" -t bug --objective "Prevent NameError in handler"
        st create --from plan.json  # Import plan (with or without subtasks)
        st create --from tasks.json --dry-run
    """
    if from_file:
        # Route plan.json files through import pipeline
        from .tasks_import import import_plan_file

        try:
            content = from_file.read_text()
            data = json.loads(content)
        except (FileNotFoundError, json.JSONDecodeError):
            # Let create_from_file or import_plan_file handle the error
            data = {}

        if "objective" in data or "subtasks" in data:
            # Plan schema — route through import pipeline
            client = STClient()
            task, task_id = import_plan_file(from_file, dry_run, None, client)
            cmplx = task.get("complexity", "SIMPLE")
            subtask_count = len(task.get("subtasks", []))
            suffix = f"{subtask_count} subtasks" if subtask_count else "intent-only"
            typer.echo(f"IMPORT:{task_id}|{cmplx}|{suffix}")
        else:
            # Batch tasks schema — route through batch create
            create_from_file(from_file, dry_run)
        return

    if not title:
        output_error("Either provide a title or use --from-file/--from")
        raise typer.Exit(1)

    if dry_run:
        output_error("--dry-run only works with --from-file/--from")
        raise typer.Exit(1)

    client = STClient()
    data = _build_task_data(
        title, task_type, priority, description, labels, parent, autonomous,
        objective=objective, spirit_anti=spirit_anti,
        done_when=done_when, complexity=complexity,
    )

    try:
        task = client.create_task(data)
    except APIError as e:
        handle_api_error(e)
        return

    if plan:
        task = _apply_plan(client, task, plan)
    if blocked_by:
        task = _apply_blocked_by(client, task, blocked_by)

    output_task(task)
