"""Task import and batch creation helpers."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_error
from .tasks_validation import validate_plan_schema, validate_task_item


def create_from_file(file_path: Path, dry_run: bool) -> None:
    """Create tasks from a JSON file."""
    # Read and parse JSON
    try:
        content = file_path.read_text()
        data = json.loads(content)
    except FileNotFoundError:
        output_error(f"File not found: {file_path}")
        raise typer.Exit(1) from None
    except json.JSONDecodeError as e:
        output_error(f"Invalid JSON at line {e.lineno}: {e.msg}")
        raise typer.Exit(1) from None

    # Extract tasks array
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

    # Validate all items
    all_errors: list[str] = []
    for i, item in enumerate(items):
        all_errors.extend(validate_task_item(item, i))

    if all_errors:
        output_error("Validation errors:")
        for err in all_errors:
            typer.echo(f"  {err}", err=True)
        raise typer.Exit(1)

    # Dry run - show summary
    if dry_run:
        typer.echo(f"Would create {len(items)} task(s):")
        for i, item in enumerate(items):
            title = item.get("title", "?")
            ttype = item.get("task_type", "task")
            subtask_count = len(item.get("subtasks", []))
            typer.echo(f"  [{i + 1}] {title} ({ttype})", nl=False)
            if subtask_count:
                typer.echo(f" - {subtask_count} subtask(s)")
            else:
                typer.echo()
        return

    # Create tasks via batch API
    client = STClient()
    try:
        result = client.batch_create_tasks(items)
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    created = result.get("created", [])
    errors = result.get("errors", [])

    # Output results
    typer.echo(f"Creating {len(items)} task(s) from {file_path}...")
    for task in created:
        task_id = task.get("id", "?")
        title = task.get("title", "?")
        typer.echo(f"  ✓ {task_id}: {title}")

    for err in errors:
        title = err.get("title", "?")
        error_msg = err.get("error", "Unknown error")
        typer.echo(f"  ✗ {title}: {error_msg}", err=True)

    typer.echo()
    typer.echo(f"Created: {len(created)}/{len(items)} tasks")
    if errors:
        typer.echo(f"Errors: {len(errors)}")
        raise typer.Exit(1)


def import_plan_file(
    file_path: Path, dry_run: bool, task_id: str | None, client: STClient
) -> tuple[dict[str, Any], str]:
    """Import a plan.json file and create or update task.

    Returns:
        Tuple of (task_dict, task_id)
    """
    import jsonschema as js

    # Read the plan file
    try:
        content = file_path.read_text()
        plan = json.loads(content)
    except FileNotFoundError:
        output_error(f"File not found: {file_path}")
        raise typer.Exit(1) from None
    except json.JSONDecodeError as e:
        output_error(f"Invalid JSON at line {e.lineno}: {e.msg}")
        raise typer.Exit(1) from None

    # Fetch schema and validate
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

    # Validate plan schema (conditional requirements and dependencies)
    issues = validate_plan_schema(plan)
    if issues:
        output_error("FAIL: Plan validation failed")
        for issue in issues:
            typer.echo(f"  - {issue}", err=True)
        raise typer.Exit(1)

    complexity = plan.get("complexity", "SIMPLE")
    subtasks = plan.get("subtasks", [])

    # Dry run - show what would be created
    if dry_run:
        typer.echo(f"Would create task: {plan.get('title')}")
        typer.echo(f"  complexity: {complexity}")
        typer.echo(f"  objective: {plan.get('objective', '')[:60]}...")
        typer.echo(f"  subtasks: {len(subtasks)}")
        for st in subtasks:
            typer.echo(f"    {st.get('id')}: {st.get('description', '')[:50]}")
        raise typer.Exit(0)

    # Build task data
    task_data: dict[str, Any] = {
        "title": plan["title"],
        "description": plan.get("description"),
        "task_type": plan.get("task_type", "task"),
        "priority": plan.get("priority", 2),
        "complexity": complexity,
        "autonomous": plan.get("autonomous", True),
    }

    # Build subtasks with step-level specs (only if subtasks present)
    subtasks_data = []
    if subtasks:
        for st in subtasks:
            subtask_id = st["id"]
            steps = st.get("steps", [])

            subtask_data: dict[str, Any] = {
                "subtask_id": subtask_id,
                "phase": st.get("phase"),
                "description": st["description"],
                "steps": steps,
                "display_order": int(subtask_id.split(".")[0]) * 100 + int(subtask_id.split(".")[1])
                if "." in subtask_id
                else 0,
            }
            if st.get("depends_on"):
                subtask_data["depends_on"] = st["depends_on"]
            subtasks_data.append(subtask_data)

        task_data["subtasks"] = subtasks_data

    # Update existing task or create new
    if task_id:
        return _update_task_from_plan(task_id, plan, task_data, subtasks_data, client)
    else:
        return _create_task_from_plan(plan, task_data, subtasks_data, client)


def _update_task_from_plan(
    task_id: str,
    plan: dict[str, Any],
    task_data: dict[str, Any],
    subtasks: list[dict[str, Any]],
    client: STClient,
) -> tuple[dict[str, Any], str]:
    """Update existing task from plan data."""
    try:
        # 1. Verify task exists
        existing = client.get_task(task_id)
        if not existing:
            output_error(f"Task not found: {task_id}")
            raise typer.Exit(1)

        # 2. Update task fields
        update_fields = {k: v for k, v in task_data.items() if k != "subtasks" and v is not None}
        client.update_task(task_id, **update_fields)

        if subtasks:
            # 3. Delete existing subtasks
            existing_subtasks = client.get_subtasks(task_id).get("subtasks", [])
            for sub in existing_subtasks:
                with contextlib.suppress(APIError):
                    client.delete_subtask(task_id, sub["subtask_id"])

            # 4. Create new subtasks
            for sub in subtasks:
                phase_val = sub.get("phase")
                client.create_subtask(
                    task_id,
                    sub["subtask_id"],
                    sub["description"],
                    phase=phase_val if phase_val else "",
                    steps=sub.get("steps", []),
                )

            # 5. Handle subtask dependencies
            _create_subtask_dependencies(task_id, subtasks)

        # 6. Upsert task_spirit
        _upsert_task_spirit(task_id, plan)

        task = client.get_task(task_id)
        return task, task_id

    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None


def _create_task_from_plan(
    plan: dict[str, Any],
    task_data: dict[str, Any],
    subtasks: list[dict[str, Any]],
    client: STClient,
) -> tuple[dict[str, Any], str]:
    """Create new task from plan data."""
    try:
        result = client.batch_create_tasks([task_data])
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    created = result.get("created", [])
    errors = result.get("errors", [])

    if errors:
        for err in errors:
            output_error(f"Failed: {err.get('error')}")
        raise typer.Exit(1)

    if not created:
        output_error("No task created")
        raise typer.Exit(1)

    task = created[0]
    task_id = task["id"]

    # Write to task_spirit table
    _upsert_task_spirit(task_id, plan)

    return task, task_id


def _upsert_task_spirit(task_id: str, plan: dict[str, Any]) -> None:
    """Upsert task_spirit record for plan data."""
    from app.storage.task_spirit import upsert_task_spirit

    try:
        plan_context = plan.get("context", {})
        context_blob = {
            "risks": plan_context.get("risks", []),
            "files_to_create": plan_context.get("files_to_create", []),
            "files_to_modify": plan_context.get("files_to_modify", []),
            "references": plan_context.get("references", []),
            "testing_strategy": plan_context.get("testing_strategy"),
        }
        context_blob = {k: v for k, v in context_blob.items() if v}

        complexity = plan.get("complexity", "SIMPLE")
        upsert_task_spirit(
            task_id=task_id,
            objective=plan["objective"],
            spirit_anti=plan.get("spirit_anti"),
            decisions=plan.get("decisions"),
            constraints=plan.get("constraints"),
            done_when=plan.get("done_when"),
            context=context_blob if context_blob else None,
            complexity=complexity,
        )
    except Exception as e:
        typer.echo(f"  Warning: Failed to write task_spirit: {e}")


def _create_subtask_dependencies(task_id: str, subtasks: list[dict[str, Any]]) -> None:
    """Create subtask dependencies from plan data."""
    from app.storage.subtask_dependencies import bulk_add_dependencies

    dependencies: list[tuple[str, str]] = []
    for sub in subtasks:
        if sub.get("depends_on"):
            full_subtask_id = f"{task_id}-{sub['subtask_id']}"
            for dep in sub["depends_on"]:
                full_dep_id = f"{task_id}-{dep}"
                dependencies.append((full_subtask_id, full_dep_id))
    if dependencies:
        try:
            bulk_add_dependencies(dependencies)
        except Exception as dep_err:
            typer.echo(f"  Warning: Failed to create dependencies: {dep_err}")
