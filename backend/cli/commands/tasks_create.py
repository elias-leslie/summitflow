"""Task creation command implementation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_error, output_task
from .tasks_import import create_from_file


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
) -> None:
    """Create a new task or batch create from file.

    Examples:
        st create "Fix bug" -t bug -p 2 -l "complexity:small,domains:backend"
        st create "Add feature" -t feature -p 1 --parent task-abc123
        st create "Implement X" --blocked-by task-abc123
        st create "AutoTest" --autonomous  # Enable autonomous execution
        st create --from-file tasks.json
        st create --from-file tasks.json --dry-run
    """
    # Handle --from-file mode
    if from_file:
        create_from_file(from_file, dry_run)
        return

    # Regular single-task creation requires title
    if not title:
        output_error("Either provide a title or use --from-file")
        raise typer.Exit(1)

    if dry_run:
        output_error("--dry-run only works with --from-file")
        raise typer.Exit(1)

    client = STClient()

    data: dict[str, Any] = {
        "title": title,
        "task_type": task_type,
        "priority": priority,
    }
    if description:
        data["description"] = description
    if labels:
        data["labels"] = labels.split(",")
    if parent:
        data["parent_task_id"] = parent
    if autonomous:
        data["autonomous"] = True

    try:
        task = client.create_task(data)
    except APIError as e:
        handle_api_error(e)
        return

    if plan:
        # Update with plan_content
        try:
            plan_content = json.loads(plan)
            task = client.update_task(task["id"], plan_content=plan_content)
        except (json.JSONDecodeError, APIError) as e:
            output_error(f"Failed to set plan: {e}")

    # Create blocking dependency if --blocked-by provided
    if blocked_by:
        try:
            client.add_dependency(task["id"], blocked_by, dep_type="blocks")
            task["blocked_by"] = blocked_by
        except APIError as e:
            task["dependency_error"] = e.detail

    output_task(task)
