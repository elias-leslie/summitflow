"""Task import and batch creation helpers."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

import typer

from ..client import APIError, STClient
from ..config import get_config
from ..output import handle_api_error, output_error, require_explicit_project
from .tasks_helpers import (
    build_subtasks_data,
    create_subtask_dependencies,
    upsert_task_spirit_from_plan,
)
from .tasks_validation import validate_plan_schema, validate_task_item


def _load_json_file(file_path: Path) -> Any:
    """Read and parse a JSON file, exiting on error."""
    try:
        return json.loads(file_path.read_text())
    except FileNotFoundError:
        output_error(f"File not found: {file_path}")
        raise typer.Exit(1) from None
    except json.JSONDecodeError as e:
        output_error(f"Invalid JSON at line {e.lineno}: {e.msg}")
        raise typer.Exit(1) from None


def create_from_file(file_path: Path, dry_run: bool) -> None:
    """Create tasks from a JSON file."""
    require_explicit_project(get_config())
    data = _load_json_file(file_path)
    if "tasks" not in data:
        output_error("JSON must contain a 'tasks' array")
        raise typer.Exit(1) from None
    items = data["tasks"]
    if not isinstance(items, list):
        output_error("'tasks' must be an array")
        raise typer.Exit(1) from None
    if not items:
        output_error("'tasks' array is empty")
        raise typer.Exit(1) from None
    all_errors: list[str] = []
    for i, item in enumerate(items):
        all_errors.extend(validate_task_item(item, i))
    if all_errors:
        output_error("Validation errors:")
        for err in all_errors:
            typer.echo(f"  {err}", err=True)
        raise typer.Exit(1)
    if dry_run:
        typer.echo(f"Would create {len(items)} task(s):")
        for i, item in enumerate(items):
            n = len(item.get("subtasks", []))
            suffix = f" - {n} subtask(s)" if n else ""
            typer.echo(f"  [{i + 1}] {item.get('title', '?')} ({item.get('task_type', 'task')}){suffix}")
        return
    client = STClient()
    try:
        result = client.batch_create_tasks(items)
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None
    created, errors = result.get("created", []), result.get("errors", [])
    typer.echo(f"Creating {len(items)} task(s) from {file_path}...")
    for task in created:
        typer.echo(f"  \u2713 {task.get('id', '?')}: {task.get('title', '?')}")
    for err in errors:
        typer.echo(f"  \u2717 {err.get('title', '?')}: {err.get('error', 'Unknown error')}", err=True)
    typer.echo()
    typer.echo(f"Created: {len(created)}/{len(items)} tasks")
    if errors:
        typer.echo(f"Errors: {len(errors)}")
        raise typer.Exit(1)


def _validate_plan(plan: Any, client: STClient) -> None:
    """Run JSON-schema and domain validation on a plan dict."""
    import jsonschema as js
    try:
        schema = client.get(f"{client.base_url}/schemas/plan")
    except APIError as e:
        output_error(f"Failed to fetch schema: {e.detail}")
        raise typer.Exit(1) from None
    try:
        js.validate(plan, schema)
    except js.ValidationError as e:
        path = ".".join(str(p) for p in e.absolute_path) if e.absolute_path else "root"
        output_error(f"Schema validation failed: {path}: {e.message}")
        raise typer.Exit(1) from None
    issues = validate_plan_schema(plan)
    if issues:
        output_error("FAIL: Plan validation failed")
        for issue in issues:
            typer.echo(f"  - {issue}", err=True)
        raise typer.Exit(1)


def _refresh_imported_task(task_id: str, client: STClient) -> dict[str, Any]:
    """Fetch the current task snapshot and attach subtasks for import reporting."""
    task = client.get_task(task_id)
    subtasks = client.get_subtasks(task_id).get("subtasks", [])
    if subtasks:
        task["subtasks"] = subtasks
    return task


def import_plan_file(
    file_path: Path, dry_run: bool, task_id: str | None, client: STClient
) -> tuple[dict[str, Any], str]:
    """Import a plan.json file and create or update task, returning (task_dict, task_id)."""
    plan = _load_json_file(file_path)
    _validate_plan(plan, client)
    if dry_run:
        subtasks = plan.get("subtasks", [])
        typer.echo(f"Would create task: {plan.get('title')}")
        typer.echo(f"  complexity: {plan.get('complexity', 'SIMPLE')}")
        typer.echo(f"  objective: {plan.get('objective', '')[:60]}...")
        typer.echo(f"  subtasks: {len(subtasks)}")
        for st in subtasks:
            typer.echo(f"    {st.get('id')}: {st.get('description', '')[:50]}")
        raise typer.Exit(0)
    subtasks_data = build_subtasks_data(plan.get("subtasks", []))
    task_data: dict[str, Any] = {
        "title": plan["title"], "description": plan.get("description"),
        "task_type": plan.get("task_type", "task"), "priority": plan.get("priority", 2),
        "complexity": plan.get("complexity", "SIMPLE"), "autonomous": plan.get("autonomous", True),
    }
    if subtasks_data:
        task_data["subtasks"] = subtasks_data
    if task_id:
        return _update_task_from_plan(task_id, plan, task_data, subtasks_data, client)
    return _create_task_from_plan(plan, task_data, subtasks_data, client)


def _update_task_from_plan(
    task_id: str, plan: dict[str, Any], task_data: dict[str, Any],
    subtasks: list[dict[str, Any]], client: STClient,
) -> tuple[dict[str, Any], str]:
    """Update existing task from plan data."""
    try:
        if not client.get_task(task_id):
            output_error(f"Task not found: {task_id}")
            raise typer.Exit(1)
        update_fields = {k: v for k, v in task_data.items() if k != "subtasks" and v is not None}
        client.update_task(task_id, **update_fields)
        if subtasks:
            _replace_subtasks(task_id, subtasks, client)
            create_subtask_dependencies(task_id, subtasks)
        upsert_task_spirit_from_plan(task_id, plan)
        return _refresh_imported_task(task_id, client), task_id
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None


def _replace_subtasks(task_id: str, subtasks: list[dict[str, Any]], client: STClient) -> None:
    """Delete existing subtasks then create new ones."""
    for sub in client.get_subtasks(task_id).get("subtasks", []):
        with contextlib.suppress(APIError):
            client.delete_subtask(task_id, sub["subtask_id"])
    for sub in subtasks:
        phase_val = sub.get("phase")
        client.create_subtask(
            task_id, sub["subtask_id"], sub["description"],
            phase=phase_val if phase_val else "", steps=sub.get("steps", []),
            subtask_type=sub.get("subtask_type"),
        )


def _create_task_from_plan(
    plan: dict[str, Any], task_data: dict[str, Any],
    subtasks: list[dict[str, Any]], client: STClient,
) -> tuple[dict[str, Any], str]:
    """Create new task from plan data."""
    try:
        result = client.batch_create_tasks([task_data])
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None
    for err in result.get("errors", []):
        output_error(f"Failed: {err.get('error')}")
    if result.get("errors"):
        raise typer.Exit(1)
    created = result.get("created", [])
    if not created:
        output_error("No task created")
        raise typer.Exit(1)
    task = created[0]
    upsert_task_spirit_from_plan(task["id"], plan)
    return _refresh_imported_task(task["id"], client), task["id"]
