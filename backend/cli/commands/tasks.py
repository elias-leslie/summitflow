"""Task commands for the CLI."""

from __future__ import annotations

import contextlib
import json
from datetime import UTC
from pathlib import Path
from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..output import (
    handle_api_error,
    output_blocked_tasks,
    output_context,
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
    blocked_by: Annotated[
        str | None,
        typer.Option("--blocked-by", help="Task ID that blocks this task"),
    ] = None,
) -> None:
    """Create a new task or batch create from file.

    Examples:
        st create "Fix bug" -t bug -p 2 -l "complexity:small,domains:backend"
        st create "Add feature" -t feature -p 1 --parent task-abc123
        st create "Implement X" --blocked-by task-abc123
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

    # Create blocking dependency if --blocked-by provided
    if blocked_by:
        try:
            client.add_dependency(task["id"], blocked_by, dep_type="blocks")
            task["blocked_by"] = blocked_by
        except APIError as e:
            task["dependency_error"] = e.detail

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
            output_blocked_tasks(blocked_tasks, blockers_map)
        else:
            result = client.list_ready(limit=limit)
            output_task_list(result["tasks"], header="READY")
    except APIError as e:
        handle_api_error(e)
        return


@app.command()
def show(
    task_ids: Annotated[list[str], typer.Argument(help="One or more task IDs")],
    full: Annotated[
        bool, typer.Option("--full", "-f", help="Show everything: subtasks, steps, progress log")
    ] = False,
    summary: Annotated[
        bool, typer.Option("--summary", "-s", help="One-liner: id|title|status|done/total|priority")
    ] = False,
) -> None:
    """Show task details with subtask progress.

    Supports multiple task IDs for batch inspection in a single call.
    Works from any directory - no project context required.

    Examples:
        st show task-abc123
        st show task-abc123 --summary  # One-liner with title and priority
        st show task-abc123 --full     # Shows all details including progress log
        st show task-abc123 task-def456  # Multiple tasks
    """
    # Use require_project=False since show uses global task lookup
    client = STClient(require_project=False)

    for task_id in task_ids:
        try:
            task = client.get_task(task_id)

            # Fetch task_spirit for context summary
            from app.storage.task_spirit import get_task_spirit

            spirit = get_task_spirit(task_id)
            if spirit:
                task["plan_status"] = spirit.get("plan_status", "draft")
                task["context"] = spirit.get("context")
                # Merge spirit fields if available
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

            # Subtasks endpoint is project-scoped, so use task's project_id
            task_project_id = task.get("project_id")
            if task_project_id and client.project_id != task_project_id:
                # Create a project-scoped client for subtasks
                subtask_client = STClient(project_id=task_project_id, require_project=False)
                subtask_data = subtask_client.get_subtasks(task_id, include_steps=True)
            else:
                subtask_data = client.get_subtasks(task_id, include_steps=True)
        except APIError as e:
            handle_api_error(e)
            continue

        # Summary mode: one-liner output
        if summary:
            ss = subtask_data.get("summary", {})
            done = ss.get("completed", 0)
            total = ss.get("total", 0)
            title = task.get("title", "")[:40]  # Truncate long titles
            status = task.get("status", "unknown")
            priority = task.get("priority", 2)
            typer.echo(f"{task_id}|{title}|{status}|{done}/{total}|P{priority}")
            continue

        # Merge subtask info into task for output
        subtasks = subtask_data.get("subtasks", [])
        summary_data = subtask_data.get("summary", {})

        task["subtasks"] = subtasks
        task["subtask_summary"] = summary_data

        # Include full details if requested
        if full:
            task["full_mode"] = True

        output_task(task)

        # Add separator between tasks if multiple
        if len(task_ids) > 1 and task_id != task_ids[-1]:
            typer.echo("---")


@app.command()
def inspect(
    task_ids: Annotated[list[str], typer.Argument(help="One or more task IDs")],
) -> None:
    """Quick one-liner inspection of tasks.

    Returns a compact summary for each task: id|status|subtasks:done/total|steps:done/total

    Examples:
        st inspect task-abc123
        st inspect task-abc123 task-def456
    """
    client = STClient()

    for task_id in task_ids:
        try:
            task = client.get_task(task_id)
            subtask_data = client.get_subtasks(task_id, include_steps=True)
        except APIError as e:
            # Print error as inline message and continue
            typer.echo(f"{task_id}|ERROR|{e!s}")
            continue

        status = task.get("status", "unknown")
        summary = subtask_data.get("summary", {})
        subtask_done = summary.get("completed", 0)
        subtask_total = summary.get("total", 0)

        # Count steps across all subtasks
        subtasks = subtask_data.get("subtasks", [])
        steps_done = 0
        steps_total = 0
        for s in subtasks:
            step_summary = s.get("step_summary", {})
            steps_done += step_summary.get("completed", 0)
            steps_total += step_summary.get("total", 0)

        typer.echo(
            f"{task_id}|{status}|subtasks:{subtask_done}/{subtask_total}|steps:{steps_done}/{steps_total}"
        )


@app.command()
def context(
    task_id: str,
) -> None:
    """Get full task context in a single call.

    Returns task details, subtasks with steps, acceptance criteria, decisions,
    and blockers in TOON format (with --compact) or JSON.

    This is optimized for /do_it workflow - one command instead of 4+ calls.

    Examples:
        st --compact context task-abc123
        st context task-abc123
    """
    client = STClient(require_project=False)

    try:
        # Fetch task
        task = client.get_task(task_id)

        # Fetch task_spirit for normalized fields (plan_status, context, etc.)
        from app.storage.task_spirit import get_task_spirit

        spirit = get_task_spirit(task_id)
        if spirit:
            # Merge task_spirit fields into task dict for output
            task["plan_status"] = spirit.get("plan_status", "draft")
            task["plan_approved_at"] = spirit.get("plan_approved_at")
            task["plan_approved_by"] = spirit.get("plan_approved_by")
            task["context"] = spirit.get("context")
            # Also update spirit fields if they came from task_spirit
            # (these may override values from tasks table during migration)
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

        # Fetch subtasks with steps (use task's project_id)
        task_project_id = task.get("project_id")
        if task_project_id and client.project_id != task_project_id:
            subtask_client = STClient(project_id=task_project_id, require_project=False)
            subtask_data = subtask_client.get_subtasks(task_id, include_steps=True)
        else:
            subtask_data = client.get_subtasks(task_id, include_steps=True)

        subtasks = subtask_data.get("subtasks", [])

        # Criteria system removed - verification now at step level
        criteria: list[dict] = []

        # Fetch blockers (dependencies where this task is blocked by others)
        deps = client.list_dependencies(task_id)
        blockers = []
        for d in deps:
            if d.get("dependency_type") == "blocks" and d.get("depends_on_status") not in (
                "completed",
                "cancelled",
            ):
                # Fetch blocker task details
                blocker_id = d.get("depends_on_task_id")
                if blocker_id:
                    try:
                        blocker_task = client.get_task(blocker_id)
                        blockers.append(blocker_task)
                    except APIError:
                        blockers.append({"id": blocker_id, "status": "unknown", "title": "?"})

    except APIError as e:
        handle_api_error(e)
        return

    output_context(task, subtasks, criteria, blockers, amendments=[])


@app.command()
def export(
    task_id: str,
    output: Annotated[
        str | None,
        typer.Option("-o", "--output", help="Output file path (default: stdout)"),
    ] = None,
) -> None:
    """Export complete task details to JSON file.

    Exports everything: task metadata, objective, spirit, constraints, done_when,
    decisions, subtasks with all steps, acceptance criteria, dependencies,
    blockers, and progress log.

    This is the single-command full export for task archival or comparison.

    Examples:
        st export task-abc123                      # Output to stdout
        st export task-abc123 -o task.json        # Write to file
        st export task-abc123 -o /tmp/task.json   # Write to specific path
    """
    from datetime import datetime

    client = STClient(require_project=False)

    try:
        # Fetch task with full details
        task = client.get_task(task_id)

        # Fetch subtasks with steps
        task_project_id = task.get("project_id")
        if task_project_id and client.project_id != task_project_id:
            subtask_client = STClient(project_id=task_project_id, require_project=False)
            subtask_data = subtask_client.get_subtasks(task_id, include_steps=True)
        else:
            subtask_data = client.get_subtasks(task_id, include_steps=True)

        subtasks = subtask_data.get("subtasks", [])

        # Criteria system removed - verification now at step level
        criteria: list[dict] = []

        # Fetch dependencies
        deps = client.list_dependencies(task_id)

        # Fetch blockers (dependencies where this task is blocked by others)
        blockers = []
        for d in deps:
            if d.get("dependency_type") == "blocks" and d.get("depends_on_status") not in (
                "completed",
                "cancelled",
            ):
                blocker_id = d.get("depends_on_task_id")
                if blocker_id:
                    try:
                        blocker_task = client.get_task(blocker_id)
                        blockers.append(blocker_task)
                    except APIError:
                        blockers.append({"id": blocker_id, "status": "unknown", "title": "?"})

        # Progress log is already included in task response
        progress_log_raw = task.get("progress_log") or ""
        progress_log = [line.strip() for line in progress_log_raw.split("\n") if line.strip()]

    except APIError as e:
        handle_api_error(e)
        return

    # Build complete export structure
    export_data = {
        "exported_at": datetime.now(UTC).isoformat(),
        "task": {
            "id": task.get("id"),
            "title": task.get("title"),
            "description": task.get("description"),
            "status": task.get("status"),
            "priority": task.get("priority"),
            "task_type": task.get("task_type"),
            "complexity": task.get("complexity"),
            "project_id": task.get("project_id"),
            "objective": task.get("objective"),
            "spirit_anti": task.get("spirit_anti"),
            "done_when": task.get("done_when") or [],
            "constraints": task.get("constraints") or [],
            "decisions": task.get("decisions") or [],
            "risks": task.get("risks") or [],
            "files_to_create": task.get("files_to_create") or [],
            "files_to_modify": task.get("files_to_modify") or [],
            "context": task.get("context") or {},
            "branch": task.get("branch"),
            "pr_url": task.get("pr_url"),
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
        },
        "subtasks": subtasks,
        "acceptance_criteria": criteria,
        "dependencies": deps,
        "blockers": blockers,
        "progress_log": progress_log,
    }

    # Output
    json_str = json.dumps(export_data, indent=2, default=str)

    if output:
        output_path = Path(output)
        output_path.write_text(json_str)
        output_success(f"Exported to {output_path}")
    else:
        print(json_str)


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
    objective: Annotated[
        str | None, typer.Option("--objective", help="Task objective (spirit statement)")
    ] = None,
    branch: Annotated[str | None, typer.Option("--branch", help="Git branch name")] = None,
    pr_url: Annotated[str | None, typer.Option("--pr-url", help="Pull request URL")] = None,
    parent: Annotated[str | None, typer.Option("--parent", help="Parent task ID")] = None,
    blocked_by: Annotated[
        str | None, typer.Option("--blocked-by", help="Add blocking dependency on task ID")
    ] = None,
    unblock: Annotated[
        str | None, typer.Option("--unblock", help="Remove blocking dependency on task ID")
    ] = None,
    spirit_anti: Annotated[str | None, typer.Option("--spirit-anti", help="What NOT to do")] = None,
    done_when: Annotated[
        list[str] | None, typer.Option("--done-when", help="Completion conditions (repeatable)")
    ] = None,
    complexity: Annotated[
        str | None, typer.Option("--complexity", help="SIMPLE, STANDARD, or COMPLEX")
    ] = None,
    decisions_json: Annotated[
        str | None, typer.Option("--decisions", help="Decisions as JSON array")
    ] = None,
    constraints_json: Annotated[
        str | None, typer.Option("--constraints", help="Constraints as JSON array")
    ] = None,
) -> None:
    """Update a task.

    Examples:
        st update task-abc123 --status running
        st update task-abc123 -p 1 -l "complexity:large"
        st update task-abc123 --add-label auto-generated
        st update task-abc123 --remove-label tier:1 --add-label tier:2
        st update task-abc123 --move-to other-project
        st update task-abc123 --objective "Enable X to do Y"
        st update task-abc123 --branch feature/auth --pr-url https://github.com/...
        st update task-abc123 --blocked-by task-def456
        st update task-abc123 --unblock task-def456
    """
    client = STClient()

    # Build update data
    updates: dict = {}
    status_to_update = status  # Handle status with other updates, not separately

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
    if objective:
        updates["objective"] = objective
    if branch:
        updates["branch_name"] = branch
    if pr_url:
        updates["pull_request_url"] = pr_url
    if parent:
        updates["parent_task_id"] = parent
    if spirit_anti:
        updates["spirit_anti"] = spirit_anti
    if done_when:
        updates["done_when"] = done_when
    if complexity:
        if complexity.upper() not in ("SIMPLE", "STANDARD", "COMPLEX"):
            output_error("complexity must be SIMPLE, STANDARD, or COMPLEX")
            raise typer.Exit(1)
        updates["complexity"] = complexity.upper()
    if decisions_json:
        import json

        try:
            updates["decisions"] = json.loads(decisions_json)
        except json.JSONDecodeError as e:
            output_error(f"Invalid decisions JSON: {e}")
            raise typer.Exit(1) from None
    if constraints_json:
        import json

        try:
            updates["constraints"] = json.loads(constraints_json)
        except json.JSONDecodeError as e:
            output_error(f"Invalid constraints JSON: {e}")
            raise typer.Exit(1) from None

    # Handle dependency operations (can be standalone or combined with other updates)
    dep_result = {}
    if blocked_by:
        try:
            client.add_dependency(task_id, blocked_by, dep_type="blocks")
            dep_result["blocked_by_added"] = blocked_by
        except APIError as e:
            dep_result["blocked_by_error"] = e.detail

    if unblock:
        try:
            client.remove_dependency(task_id, unblock)
            dep_result["unblocked"] = unblock
        except APIError as e:
            dep_result["unblock_error"] = e.detail

    # If only dependency operations (no other updates, no status)
    if not updates and not status_to_update and (blocked_by or unblock):
        try:
            task = client.get_task(task_id)
            task.update(dep_result)
            output_task(task)
            return
        except APIError as e:
            handle_api_error(e)
            return

    if not updates and not status_to_update:
        output_error("No updates specified")
        raise typer.Exit(1)

    task = None
    # Apply field updates first
    if updates:
        try:
            task = client.update_task(task_id, **updates)
        except APIError as e:
            handle_api_error(e)
            return

    # Apply status update (uses separate endpoint)
    if status_to_update:
        # Pre-check: if transitioning to 'running', verify plan is approved
        if status_to_update == "running":
            from app.storage.task_spirit import get_task_spirit

            spirit = get_task_spirit(task_id)
            if spirit:
                plan_status = spirit.get("plan_status", "draft")
                if plan_status != "approved":
                    output_error(
                        f"Plan not approved (status: {plan_status}). Run: st approve {task_id}"
                    )
                    raise typer.Exit(1)

        try:
            task = client.update_status(task_id, status_to_update)
        except APIError as e:
            handle_api_error(e)
            return

    # Fetch task if neither update was done but we have dep operations
    if task is None:
        try:
            task = client.get_task(task_id)
        except APIError as e:
            handle_api_error(e)
            return

    task.update(dep_result)
    output_task(task)


@app.command()
def close(
    task_id: Annotated[str | None, typer.Argument()] = None,
    reason: Annotated[str | None, typer.Option("-r", "--reason")] = None,
) -> None:
    """Close a task (mark as completed).

    All subtasks must be complete and all acceptance criteria must be verified.
    QA must be passed or skipped. There is no bypass - if gates fail, complete the work first.

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st close task-abc123 -r "All subtasks completed"
        st close -r "Done"    # Uses active context
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    # Pre-check: verify QA status before attempting close
    try:
        task_data = client.get_task(task_id)
        qa_status = task_data.get("qa_status", "pending")
        if qa_status not in ("passed", "skipped"):
            output_error(
                f"QA not passed (status: {qa_status}). "
                f"Run: st qa pass {task_id} (or st qa skip {task_id})"
            )
            raise typer.Exit(1)
    except APIError:
        pass  # Continue - let close_task handle any errors

    try:
        task = client.close_task(task_id, reason=reason)
    except APIError as e:
        # Parse error detail - might be dict with what_to_do instructions
        detail = e.detail
        if isinstance(detail, dict):
            # Structured error with guidance
            output_json(
                {
                    "error": detail.get("message", "Task close failed"),
                    "what_to_do": detail.get("what_to_do", []),
                    "incomplete_subtasks": detail.get("incomplete_subtasks", []),
                    "unverified_criteria": detail.get("unverified_criteria", []),
                }
            )
        else:
            # Simple string error
            detail_lower = detail.lower() if isinstance(detail, str) else ""
            hints: list[str] = []

            if "status" in detail_lower or "transition" in detail_lower:
                hints.append("Check task status with 'st show <id>'")
                hints.append("Use 'st cancel <id>' for non-terminal states")

            if "not found" in detail_lower:
                hints.append("Verify task ID with 'st list'")

            output_json({"error": detail, "hints": hints})
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
    agent: Annotated[
        bool, typer.Option("--agent", help="Create worktree for agent execution")
    ] = False,
) -> None:
    """Claim or release a task.

    Use --agent to create an isolated git worktree for agent execution.
    The worktree will be created at .worktrees/exec/{task_id}/.

    Examples:
        st claim task-abc123 --lock 60
        st claim task-abc123 --release
        st claim task-abc123 --agent
    """
    from ..config import get_config

    client = STClient()

    try:
        if release:
            task = client.release_task(task_id)
            task["action"] = "released"
        elif agent:
            # Claim with worktree creation for agent execution
            from app.services.git_service import auto_claim_with_worktree

            config = get_config()
            project_root = config.project_root or str(Path.cwd())

            worktree_info = auto_claim_with_worktree(
                task_id=task_id,
                project_path=project_root,
                project_id=config.project_id,
            )

            task = client.get_task(task_id)
            task["action"] = "claimed_with_worktree"
            task["worktree_path"] = worktree_info["worktree_path"]
            task["branch_name"] = worktree_info["branch_name"]
            task["base_sha"] = worktree_info["base_sha"]
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


@app.command("verify")
def verify_plan(
    file_path: Annotated[Path, typer.Argument(help="Path to plan.json file")],
) -> None:
    """Verify a plan.json file against the schema.

    Validates:
    - JSON schema compliance
    - Conditional requirements (STANDARD/COMPLEX need done_when, COMPLEX needs decisions)

    Examples:
        st task verify tasks/my-feature/plan.json
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

    # Fetch schema from API
    client = STClient(require_project=False)
    try:
        schema = client.get(f"{client.base_url}/schemas/plan")
    except APIError as e:
        output_error(f"Failed to fetch schema: {e.detail}")
        raise typer.Exit(1) from None

    # Validate against JSON schema
    issues: list[str] = []
    try:
        js.validate(plan, schema)
    except js.ValidationError as e:
        # Extract the relevant part of the error message
        path = ".".join(str(p) for p in e.absolute_path) if e.absolute_path else "root"
        issues.append(f"Schema: {path}: {e.message}")

    # Check conditional requirements
    complexity = plan.get("complexity", "SIMPLE")

    if complexity in ("STANDARD", "COMPLEX"):
        if not plan.get("spirit_anti"):
            issues.append(f"Conditional: {complexity} tasks require 'spirit_anti'")
        done_when = plan.get("done_when", [])
        if not done_when or len(done_when) < 1:
            issues.append(
                f"Conditional: {complexity} tasks require 'done_when' with at least 1 item"
            )

    if complexity == "COMPLEX":
        decisions = plan.get("decisions", [])
        if not decisions or len(decisions) < 1:
            issues.append("Conditional: COMPLEX tasks require 'decisions' with at least 1 item")

    # Context validation handled by JSON schema (additionalProperties: false)

    # Collect valid subtask IDs for dependency validation
    subtasks = plan.get("subtasks", [])
    valid_subtask_ids = {s.get("id") for s in subtasks if s.get("id")}

    # Validate depends_on references point to valid subtask IDs
    for subtask in subtasks:
        subtask_id = subtask.get("id", "?")
        depends_on = subtask.get("depends_on", [])
        if depends_on:
            for dep in depends_on:
                if dep not in valid_subtask_ids:
                    issues.append(f"subtask {subtask_id} depends_on '{dep}' which doesn't exist")
                if dep == subtask_id:
                    issues.append(f"subtask {subtask_id} cannot depend on itself")

    # Validate criterion-subtask mapping if acceptance_criteria have subtask_ids
    ac_list = plan.get("acceptance_criteria", [])
    for ac in ac_list:
        ac_id = ac.get("id", "?")
        subtask_ids = ac.get("subtask_ids", [])
        if subtask_ids:
            for sid in subtask_ids:
                if sid not in valid_subtask_ids:
                    issues.append(
                        f"criterion {ac_id} references subtask '{sid}' which doesn't exist"
                    )

    # Output result
    if issues:
        typer.echo("FAIL")
        for issue in issues:
            typer.echo(f"  - {issue}", err=True)
        raise typer.Exit(1)
    else:
        typer.echo("PASS")
        typer.echo(f"  complexity: {complexity}")
        typer.echo(f"  subtasks: {len(plan.get('subtasks', []))}")
        if plan.get("done_when"):
            typer.echo(f"  done_when: {len(plan['done_when'])} items")


@app.command()
def autocode(
    task_id: str,
    status: Annotated[
        str | None,
        typer.Option("--status", help="Get status of execution by ID"),
    ] = None,
    abort: Annotated[
        str | None,
        typer.Option("--abort", help="Abort execution by ID"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model to use for execution"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Validate only, don't execute"),
    ] = False,
) -> None:
    """Run autocode execution on a task via Agent Hub.

    Dispatches the first incomplete subtask to an AI worker for autonomous
    code generation, then validates and commits the results.

    Examples:
        st autocode task-abc123              # Start execution
        st autocode task-abc123 --dry-run    # Validate without executing
        st autocode task-abc123 --status exec-12345  # Check status
        st autocode task-abc123 --abort exec-12345   # Abort execution
        st autocode task-abc123 --model claude-opus-4-5  # Use specific model
    """
    client = STClient()

    # Status check mode
    if status:
        try:
            result = client.get_autocode_status(task_id, status)
        except APIError as e:
            handle_api_error(e)
            raise typer.Exit(1) from None

        # Format evidence summary if present
        evidence = result.get("evidence")
        if evidence:
            files = evidence.get("evidence", {}).get("files_modified", [])
            verifications = evidence.get("evidence", {}).get("verifications", [])
            passed = sum(1 for v in verifications if v.get("passed"))
            result["evidence_summary"] = {
                "files_modified": len(files),
                "verifications": f"{passed}/{len(verifications)}",
            }
            del result["evidence"]  # Remove full evidence for cleaner output

        output_json(result)
        return

    # Abort mode
    if abort:
        try:
            result = client.abort_autocode(task_id, abort)
        except APIError as e:
            handle_api_error(e)
            raise typer.Exit(1) from None

        output_json(result)
        return

    # Start execution mode
    try:
        result = client.start_autocode(task_id, model=model, dry_run=dry_run)
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    # Format evidence summary for completed executions
    if result.get("status") in ("completed", "failed"):
        output_json(result)
    else:
        # For pending/running/dry_run, output as-is
        output_json(result)


@app.command("import")
def import_plan(
    file_path: Annotated[Path, typer.Argument(help="Path to plan.json file")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Validate only, don't create")] = False,
    task_id: Annotated[
        str | None,
        typer.Option("--task", "-t", help="Update existing task instead of creating new"),
    ] = None,
) -> None:
    """Import a plan.json file as a SummitFlow task.

    First runs verify, then creates or updates the task with subtasks.

    Examples:
        st task import tasks/my-feature/plan.json
        st task import tasks/my-feature/plan.json --dry-run
        st task import tasks/my-feature/plan.json --task task-abc123
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

    # Fetch schema and validate (same as verify)
    client = STClient()
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

    # Check conditional requirements
    complexity = plan.get("complexity", "SIMPLE")
    if complexity in ("STANDARD", "COMPLEX"):
        if not plan.get("spirit_anti"):
            output_error(f"FAIL: {complexity} tasks require 'spirit_anti'")
            raise typer.Exit(1)
        if not plan.get("done_when"):
            output_error(f"FAIL: {complexity} tasks require 'done_when'")
            raise typer.Exit(1)
    if complexity == "COMPLEX" and not plan.get("decisions"):
        output_error("FAIL: COMPLEX tasks require 'decisions'")
        raise typer.Exit(1)

    # Dry run - show what would be created
    if dry_run:
        typer.echo(f"Would create task: {plan.get('title')}")
        typer.echo(f"  complexity: {complexity}")
        typer.echo(f"  objective: {plan.get('objective', '')[:60]}...")
        subtasks = plan.get("subtasks", [])
        typer.echo(f"  subtasks: {len(subtasks)}")
        for st in subtasks:
            typer.echo(f"    {st.get('id')}: {st.get('description', '')[:50]}")
        return

    # Build task data
    # Note: objective, spirit_anti, decisions, constraints, done_when go to task_spirit
    # Labels go to task_labels (handled separately)
    task_data: dict[str, Any] = {
        "title": plan["title"],
        "description": plan.get("description"),
        "task_type": plan.get("task_type", "task"),
        "priority": plan.get("priority", 2),
        "complexity": complexity,
    }

    # Build subtasks with step-level specs (no longer using subtask-level details)
    subtasks = []
    for st in plan.get("subtasks", []):
        subtask_id = st["id"]

        # Steps can be strings or {description, spec} objects
        # Pass through as-is - storage layer handles both formats
        steps = st.get("steps", [])

        subtask_data = {
            "subtask_id": subtask_id,
            "phase": st.get("phase"),
            "description": st["description"],
            "steps": steps,
            "display_order": int(subtask_id.split(".")[0]) * 100 + int(subtask_id.split(".")[1])
            if "." in subtask_id
            else 0,
        }
        # Include depends_on if specified (for subtask_dependencies table)
        if st.get("depends_on"):
            subtask_data["depends_on"] = st["depends_on"]
        subtasks.append(subtask_data)

    task_data["subtasks"] = subtasks

    # Update existing task or create new
    if task_id:
        # UPDATE existing task
        try:
            # 1. Verify task exists
            existing = client.get_task(task_id)
            if not existing:
                output_error(f"Task not found: {task_id}")
                raise typer.Exit(1)

            # 2. Update task fields
            update_fields = {
                k: v for k, v in task_data.items() if k != "subtasks" and v is not None
            }
            client.update_task(task_id, **update_fields)

            # 3. Delete existing subtasks
            existing_subtasks = client.get_subtasks(task_id).get("subtasks", [])
            for sub in existing_subtasks:
                with contextlib.suppress(APIError):
                    client.delete_subtask(task_id, sub["subtask_id"])

            # 4. Create new subtasks (step-level specs, no subtask-level details)
            for sub in subtasks:
                client.create_subtask(
                    task_id,
                    sub["subtask_id"],
                    sub["description"],
                    phase=sub.get("phase"),
                    steps=sub.get("steps", []),
                )

            # 5. Criteria system removed - verification now at step level
            # (criteria cleanup code removed)

            # 6. Upsert task_spirit for normalized storage
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

            # 7. Handle subtask dependencies
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

            task = client.get_task(task_id)
            typer.echo(f"{task_id} updated")

        except APIError as e:
            handle_api_error(e)
            raise typer.Exit(1) from None
    else:
        # CREATE new task via batch API
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
        typer.echo(f"{task_id} created")

    # Write to task_spirit table for normalized storage
    from app.storage.task_spirit import upsert_task_spirit

    try:
        # Build context blob for plan.json round-trip preservation
        # Context can be at plan level or nested in 'context' key
        plan_context = plan.get("context", {})
        context_blob = {
            "risks": plan_context.get("risks", []),
            "files_to_create": plan_context.get("files_to_create", []),
            "files_to_modify": plan_context.get("files_to_modify", []),
            "references": plan_context.get("references", []),
            "testing_strategy": plan_context.get("testing_strategy"),
        }
        # Remove None values and empty lists from context
        context_blob = {k: v for k, v in context_blob.items() if v}

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

    # Output summary
    typer.echo(f"  title: {task.get('title', plan['title'])}")
    typer.echo(f"  complexity: {task.get('complexity', complexity)}")
    typer.echo(f"  subtasks: {len(subtasks)}")

    # Create acceptance criteria if provided
    ac_list = plan.get("acceptance_criteria", [])
    if ac_list:
        criteria_items = []
        for ac in ac_list:
            criteria_items.append(
                {
                    "criterion": ac["criterion"],
                    "category": ac.get("category", "correctness"),
                    "verify_command": ac.get("verify_command"),
                    "verify_by": ac.get("verify_by", "test"),
                    "expected_output": ac.get("expected_output"),
                }
            )

        try:
            result = client.batch_create_task_criteria(task_id, criteria_items)
            created_count = len(result.get("created", []))
            error_count = len(result.get("errors", []))
            typer.echo(f"  criteria: {created_count} created")
            if error_count > 0:
                typer.echo(f"  criteria errors: {error_count}")
                for err in result.get("errors", []):
                    typer.echo(f"    - {err.get('criterion', '')[:30]}: {err.get('error', '')}")
        except APIError as e:
            typer.echo(f"  Warning: Failed to create criteria: {e.detail}")


@app.command()
def approve(
    task_id: str,
) -> None:
    """Approve a task's plan, allowing execution to start.

    Sets plan_status='approved' in task_spirit table.
    Tasks must be approved before they can be started (status='running').

    Examples:
        st approve task-abc123
    """
    from app.storage.task_spirit import approve_plan

    try:
        result = approve_plan(task_id, approved_by="user")
        if result:
            typer.echo(f"APPROVED: {task_id} - ready to run")
        else:
            output_error(f"Task {task_id} not found in task_spirit table")
            raise typer.Exit(1)
    except Exception as e:
        output_error(f"Failed to approve: {e}")
        raise typer.Exit(1) from None


# QA command group
qa_app = typer.Typer(help="QA signoff commands")
app.add_typer(qa_app, name="qa")


@qa_app.command("pass")
def qa_pass(
    task_id: str,
) -> None:
    """Mark QA as passed for a task.

    All acceptance criteria must be verified first.
    """
    client = STClient(require_project=False)
    try:
        client.update_task(task_id, qa_status="passed")
        # Verify the update actually took effect (DB trigger may have blocked it)
        task = client.get_task(task_id)
        if task.get("qa_status") != "passed":
            output_error(
                f"QA pass blocked by DB trigger. Current status: {task.get('qa_status')}. "
                f"Use: st criterion list --task {task_id}"
            )
            raise typer.Exit(1)
        typer.echo(f"QA:PASSED: {task_id}")
    except APIError as e:
        # Check for trigger rejection
        if "unverified criteria" in str(e.detail).lower():
            output_error(
                "Cannot pass QA with unverified criteria. Use: st criterion list --task " + task_id
            )
        else:
            handle_api_error(e)
        raise typer.Exit(1) from None


@qa_app.command("fail")
def qa_fail(
    task_id: str,
) -> None:
    """Mark QA as failed for a task."""
    client = STClient(require_project=False)
    try:
        client.update_task(task_id, qa_status="failed")
        typer.echo(f"QA:FAILED: {task_id}")
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None


@qa_app.command("skip")
def qa_skip(
    task_id: str,
) -> None:
    """Skip QA for a task.

    Only SIMPLE tasks can skip QA. STANDARD/COMPLEX tasks must pass QA.
    """
    client = STClient(require_project=False)

    # Check complexity - only SIMPLE tasks can skip
    try:
        task = client.get_task(task_id)
        complexity = task.get("complexity", "SIMPLE")
        if complexity in ("STANDARD", "COMPLEX"):
            output_error(f"Cannot skip QA for {complexity} task. Must pass QA.")
            raise typer.Exit(1)
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    try:
        client.update_task(task_id, qa_status="skipped")
        typer.echo(f"QA:SKIPPED: {task_id}")
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None


@app.command()
def work(
    task_id: Annotated[str | None, typer.Argument()] = None,
    done: Annotated[
        bool,
        typer.Option("--done", help="Clear active context"),
    ] = False,
    show: Annotated[
        bool,
        typer.Option("--show", help="Show current context"),
    ] = False,
) -> None:
    """Set or show the active task context.

    Once set, subsequent commands (close, subtask, step, criterion) will
    use this task automatically when no explicit ID is provided.

    Examples:
        st work task-abc123          # Set active task
        st work --show               # Show current context
        st work --done               # Clear active context
        st close                     # Uses active task (no ID needed)
        st subtask pass 1.1          # Uses active task
    """
    from ..context import (
        clear_active_task_id,
        get_active_context,
        set_active_task_id,
    )

    # --show: display current context
    if show:
        ctx = get_active_context()
        if ctx:
            typer.echo(f"ACTIVE:{ctx.task_id}")
            if ctx.set_at:
                typer.echo(f"  set_at: {ctx.set_at}")
            if ctx.project_id:
                typer.echo(f"  project: {ctx.project_id}")
        else:
            typer.echo("No active context")
        return

    # --done: clear context
    if done:
        if clear_active_task_id():
            typer.echo("CLEARED: active context")
        else:
            typer.echo("No active context to clear")
        return

    # Set context: requires task_id
    if not task_id:
        # No argument and no flag - show current context
        ctx = get_active_context()
        if ctx:
            typer.echo(f"ACTIVE:{ctx.task_id}")
        else:
            output_error("Usage: st work <task-id> or st work --show")
            raise typer.Exit(1)
        return

    # Validate task exists
    client = STClient(require_project=False)
    try:
        task = client.get_task(task_id)
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    # Set active context
    project_id = task.get("project_id")
    context_path = set_active_task_id(task_id, project_id)

    # Output confirmation
    typer.echo(f"ACTIVE:{task_id}")
    typer.echo(f"  title: {task.get('title', '')[:60]}")
    typer.echo(f"  status: {task.get('status', 'unknown')}")
    typer.echo(f"  context: {context_path}")
