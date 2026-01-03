"""Task commands for the CLI."""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path
from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..output import (
    handle_api_error,
    output_error,
    output_json,
    output_success,
    output_task,
    output_task_list,
)

app = typer.Typer(help="Task management commands")


def _validate_task_item(item: dict[str, Any], index: int) -> list[str]:
    """Validate a single task item and return list of errors."""
    errors: list[str] = []
    prefix = f"tasks[{index}]"

    # Required fields
    if "title" not in item or not item["title"]:
        errors.append(f"{prefix}: Missing required field 'title'")
    if "task_type" not in item or not item["task_type"]:
        errors.append(f"{prefix}: Missing required field 'task_type'")

    # Validate task_type
    valid_types = ("feature", "bug", "task", "chore")
    if item.get("task_type") and item["task_type"] not in valid_types:
        errors.append(f"{prefix}: task_type must be one of: {', '.join(valid_types)}")

    # Validate priority
    if "priority" in item:
        p = item["priority"]
        if not isinstance(p, int) or p < 0 or p > 4:
            errors.append(f"{prefix}: priority must be integer 0-4")

    # Validate subtasks if present
    if item.get("subtasks"):
        for si, subtask in enumerate(item["subtasks"]):
            sub_prefix = f"{prefix}.subtasks[{si}]"
            if "subtask_id" not in subtask:
                errors.append(f"{sub_prefix}: Missing required field 'subtask_id'")
            if "description" not in subtask:
                errors.append(f"{sub_prefix}: Missing required field 'description'")

    return errors


def _create_from_file(file_path: Path, dry_run: bool) -> None:
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
        all_errors.extend(_validate_task_item(item, i))

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


@app.command()
def create(
    title: Annotated[str | None, typer.Argument()] = None,
    from_file: Annotated[
        Path | None,
        typer.Option("--from-file", help="JSON file with tasks to create"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview without creating"),
    ] = False,
    description: Annotated[str | None, typer.Option("-d", "--description")] = None,
    priority: Annotated[int, typer.Option("-p", "--priority", min=0, max=4)] = 2,
    labels: Annotated[str | None, typer.Option("-l", "--labels")] = None,
    task_type: Annotated[str, typer.Option("-t", "--type")] = "task",
    parent: Annotated[str | None, typer.Option("--parent")] = None,
    plan: Annotated[str | None, typer.Option("--plan")] = None,
) -> None:
    """Create a new task or batch create from file.

    Examples:
        st create "Fix bug" -t bug -p 2 -l "complexity:small,domains:backend"
        st create "Add feature" -t feature -p 1 --parent task-abc123
        st create --from-file tasks.json
        st create --from-file tasks.json --dry-run
    """
    # Handle --from-file mode
    if from_file:
        _create_from_file(from_file, dry_run)
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

    output_task(task)


@app.command("list")
def list_tasks(
    status: Annotated[str | None, typer.Option("-s", "--status")] = None,
    task_type: Annotated[str | None, typer.Option("-t", "--type")] = None,
    priority: Annotated[int | None, typer.Option("-p", "--priority", min=0, max=4)] = None,
    tier: Annotated[int | None, typer.Option("--tier", min=1, max=4)] = None,
    labels: Annotated[str | None, typer.Option("-l", "--labels")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 50,
) -> None:
    """List tasks with optional filters.

    Examples:
        st list --status pending
        st list -t bug -p 1
        st list --tier 1
        st list --labels "complexity:small"
    """
    client = STClient()

    # Build labels list, adding tier filter if specified
    labels_list = labels.split(",") if labels else None
    if tier:
        tier_label = f"tier:{tier}"
        if labels_list:
            labels_list.append(tier_label)
        else:
            labels_list = [tier_label]

    try:
        result = client.list_tasks(
            status=status,
            task_type=task_type,
            priority=priority,
            labels=labels_list,
            limit=limit,
        )
    except APIError as e:
        handle_api_error(e)
        return

    output_task_list(result["tasks"])


@app.command()
def ready(
    limit: Annotated[int, typer.Option("--limit")] = 50,
    blocked: Annotated[bool, typer.Option("--blocked")] = False,
) -> None:
    """List tasks ready to work on (not blocked).

    Use --blocked to show blocked tasks instead.

    Examples:
        st ready
        st ready --blocked
        st ready --limit 10
    """
    client = STClient()

    try:
        if blocked:
            # Get pending tasks and filter to blocked ones
            result = client.list_tasks(status="pending", limit=limit * 2)
            tasks = result.get("tasks", [])

            # Filter to tasks that have blocking dependencies
            blocked_tasks = []
            blockers_map: dict[str, list[str]] = {}  # blocker_id -> [blocked_task_ids]

            for task in tasks:
                task_id = task["id"]
                deps = client.list_dependencies(task_id)

                # Find incomplete blocking dependencies
                blocking = [
                    d
                    for d in deps
                    if d.get("dependency_type") == "blocks"
                    and d.get("depends_on_status") not in ("completed", "cancelled")
                ]

                if blocking:
                    task["blockers"] = blocking
                    blocked_tasks.append(task)

                    # Track which tasks each blocker blocks
                    for b in blocking:
                        blocker_id = b.get("depends_on_task_id", "")
                        if blocker_id not in blockers_map:
                            blockers_map[blocker_id] = []
                        blockers_map[blocker_id].append(task_id)

            blocked_tasks = blocked_tasks[:limit]
            output_json({"tasks": blocked_tasks, "blockers_impact": blockers_map})
        else:
            result = client.list_ready(limit=limit)
            output_task_list(result["tasks"])
    except APIError as e:
        handle_api_error(e)
        return


@app.command()
def show(
    task_id: str,
    full: Annotated[
        bool, typer.Option("--full", "-f", help="Show everything: subtasks, steps, progress log")
    ] = False,
) -> None:
    """Show task details with subtask progress.

    Examples:
        st show task-abc123
        st show task-abc123 --full    # Shows all details including progress log
    """
    client = STClient()

    try:
        task = client.get_task(task_id)
        subtask_data = client.get_subtasks(task_id, include_steps=True)
    except APIError as e:
        handle_api_error(e)
        return

    # Merge subtask info into task for output
    subtasks = subtask_data.get("subtasks", [])
    summary = subtask_data.get("summary", {})

    task["subtasks"] = subtasks
    task["subtask_summary"] = summary

    # Include full details if requested
    if full:
        task["full_mode"] = True

    output_task(task)


@app.command()
def update(
    task_id: str,
    status: Annotated[str | None, typer.Option("-s", "--status")] = None,
    priority: Annotated[int | None, typer.Option("-p", "--priority", min=0, max=4)] = None,
    labels: Annotated[str | None, typer.Option("-l", "--labels")] = None,
    add_label: Annotated[list[str] | None, typer.Option("--add-label")] = None,
    remove_label: Annotated[list[str] | None, typer.Option("--remove-label")] = None,
    task_type: Annotated[str | None, typer.Option("-t", "--type")] = None,
    title: Annotated[str | None, typer.Option("--title")] = None,
    description: Annotated[str | None, typer.Option("-d", "--description")] = None,
    move_to: Annotated[str | None, typer.Option("--move-to")] = None,
    plan: Annotated[str | None, typer.Option("--plan")] = None,
    capability: Annotated[int | None, typer.Option("--capability")] = None,
) -> None:
    """Update a task.

    Examples:
        st update task-abc123 --status running
        st update task-abc123 -p 1 -l "complexity:large"
        st update task-abc123 --add-label auto-generated
        st update task-abc123 --remove-label tier:1 --add-label tier:2
        st update task-abc123 --move-to other-project
        st update task-abc123 --capability 615
    """
    client = STClient()

    # Handle status update separately (uses /status endpoint)
    if status:
        try:
            task = client.update_status(task_id, status)
            output_task(task)
            return
        except APIError as e:
            handle_api_error(e)
            return

    # Build update data
    updates: dict = {}
    if priority is not None:
        updates["priority"] = priority

    # Handle label modifications
    if add_label or remove_label:
        # Fetch current task to get existing labels
        try:
            current_task = client.get_task(task_id)
            current_labels = set(current_task.get("labels", []) or [])
        except APIError as e:
            handle_api_error(e)
            return

        # Remove labels first, then add
        if remove_label:
            for label in remove_label:
                current_labels.discard(label)

        if add_label:
            for label in add_label:
                current_labels.add(label)

        updates["labels"] = list(current_labels)
    elif labels:
        # Full replacement
        updates["labels"] = labels.split(",")

    if task_type:
        updates["task_type"] = task_type
    if title:
        updates["title"] = title
    if description:
        updates["description"] = description
    if move_to:
        updates["project_id"] = move_to
    if plan:
        import json

        try:
            updates["plan_content"] = json.loads(plan)
        except json.JSONDecodeError as e:
            output_error(f"Invalid plan JSON: {e}")
            raise typer.Exit(1) from None
    if capability is not None:
        updates["capability_id"] = capability

    if not updates:
        output_error("No updates specified")
        raise typer.Exit(1)

    try:
        task = client.update_task(task_id, **updates)
    except APIError as e:
        handle_api_error(e)
        return

    output_task(task)


@app.command()
def close(
    task_id: str,
    reason: Annotated[str | None, typer.Option("-r", "--reason")] = None,
    force: Annotated[bool, typer.Option("-f", "--force")] = False,
) -> None:
    """Close a task (mark as completed).

    Examples:
        st close task-abc123 -r "Fixed the bug"
        st close task-abc123 --force
    """
    client = STClient()

    try:
        task = client.close_task(task_id, reason=reason, force=force)
    except APIError as e:
        # Provide helpful hints for common errors
        detail = e.detail.lower()
        hints: list[str] = []

        if "criteria" in detail or "unverified" in detail:
            hints.append("Use --force to bypass criteria validation")
            hints.append("Or verify pending criteria first")

        if "capability" in detail:
            hints.append("Run 'st capability verify <id>' to check test status")

        if "status" in detail or "transition" in detail:
            hints.append("Check task status with 'st show <id>'")
            hints.append("Use 'st cancel <id>' for non-terminal states")

        if "not found" in detail:
            hints.append("Verify task ID with 'st list'")

        output_json({"error": e.detail, "hints": hints})
        raise typer.Exit(1) from None

    output_task(task)


@app.command()
def cancel(
    task_id: str,
    reason: Annotated[str, typer.Option("-r", "--reason")],
) -> None:
    """Cancel a task (mark as cancelled from any state).

    Use this for tasks that are invalid, obsolete, or no longer needed.
    Works from any non-terminal state (pending, running, paused, failed).

    Examples:
        st cancel task-abc123 -r "Invalid: file doesn't exist"
        st cancel task-abc123 --reason "Obsolete: already fixed"
    """
    client = STClient()

    try:
        task = client.cancel_task(task_id)
    except APIError as e:
        handle_api_error(e)
        return

    # Include the reason in the output
    task["cancel_reason"] = reason
    output_task(task)


@app.command()
def claim(
    task_id: str,
    lock: Annotated[int, typer.Option("--lock")] = 30,
    release: Annotated[bool, typer.Option("--release")] = False,
) -> None:
    """Claim or release a task.

    Examples:
        st claim task-abc123 --lock 60
        st claim task-abc123 --release
    """
    client = STClient()

    try:
        if release:
            task = client.release_task(task_id)
            task["action"] = "released"
        else:
            task = client.claim_task(task_id, lock_minutes=lock)
            task["action"] = "claimed"
            task["lock_minutes"] = lock
    except APIError as e:
        handle_api_error(e)
        return

    output_task(task)


@app.command()
def delete(
    task_id: str,
    force: Annotated[bool, typer.Option("-f", "--force")] = False,
) -> None:
    """Delete a task.

    Examples:
        st delete task-abc123
        st delete task-abc123 --force
    """
    if not force:
        confirm = typer.confirm(f"Delete task {task_id}?")
        if not confirm:
            raise typer.Abort()

    client = STClient()

    try:
        client.delete_task(task_id)
    except APIError as e:
        handle_api_error(e)
        return

    output_success(f"Deleted task {task_id}")


@app.command()
def bug(
    title: str,
    description: Annotated[str | None, typer.Option("-d", "--description")] = None,
    priority: Annotated[int, typer.Option("-p", "--priority", min=0, max=4)] = 2,
    labels: Annotated[str | None, typer.Option("-l", "--labels")] = None,
    from_task: Annotated[str | None, typer.Option("--from")] = None,
) -> None:
    """Create a bug task (shorthand for create -t bug).

    If --from is specified, creates a discovered-from dependency and
    inherits domain labels from the parent task.

    Examples:
        st bug "Fix null pointer exception" -p 1
        st bug "Missing validation" --from task-abc123
        st bug "Type error in auth" -l "complexity:small,domains:backend"
    """
    client = STClient()

    # If --from specified, fetch parent to inherit domains
    inherited_labels: list[str] = []
    if from_task:
        try:
            parent = client.get_task(from_task)
            parent_labels = parent.get("labels", [])
            # Inherit domain labels
            for label in parent_labels:
                if label.startswith("domains:"):
                    inherited_labels.append(label)
        except APIError:
            pass  # If parent not found, continue without inheriting

    # Build labels list
    all_labels: list[str] = []
    if labels:
        all_labels.extend(labels.split(","))
    # Add inherited labels that aren't already present
    for label in inherited_labels:
        if label not in all_labels:
            all_labels.append(label)

    data: dict = {
        "title": title,
        "task_type": "bug",
        "priority": priority,
    }
    if description:
        data["description"] = description
    if all_labels:
        data["labels"] = all_labels

    try:
        task = client.create_task(data)
    except APIError as e:
        handle_api_error(e)
        return

    # Create discovered-from dependency if --from specified
    if from_task:
        try:
            client.add_dependency(task["id"], from_task, dep_type="discovered-from")
            task["linked_from"] = from_task
        except APIError as e:
            task["dependency_error"] = e.detail

    output_task(task)


@app.command()
def exec(
    task_id: str,
    agent: Annotated[str, typer.Option("--agent")] = "claude",
    worktree: Annotated[bool, typer.Option("--worktree")] = False,
) -> None:
    """Start execution of a task via API.

    Triggers the autonomous execution system to work on the task.

    Examples:
        st exec task-abc123
        st exec task-abc123 --agent gemini
        st exec task-abc123 --worktree
    """
    client = STClient()

    try:
        result = client.start_execution(task_id, agent_type=agent, use_worktree=worktree)
    except APIError as e:
        handle_api_error(e)
        return

    output_json(result)


@app.command()
def log(
    task_id: str,
    message: str,
) -> None:
    """Append a log entry to a task's progress log.

    A timestamp is automatically prepended to the message.

    Examples:
        st log task-abc123 "Started working on feature"
        st log task-abc123 "Fixed issue with validation"
    """
    from datetime import datetime

    client = STClient()

    # Add timestamp prefix
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = f"[{timestamp}] {message}"

    try:
        result = client.append_log(task_id, entry)
    except APIError as e:
        handle_api_error(e)
        return

    output_json(result)
