"""Task commands for the CLI."""

from __future__ import annotations

import contextlib
import json
from datetime import UTC
from pathlib import Path
from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..lib.worktree import get_worktree_info
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
    autonomous: Annotated[
        bool,
        typer.Option("--autonomous", help="Enable autonomous execution for this task"),
    ] = False,
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


@app.command("list")
def list_tasks(
    status: Annotated[str | None, typer.Option("-s", "--status")] = None,
    task_type: Annotated[str | None, typer.Option("-t", "--type")] = None,
    priority: Annotated[int | None, typer.Option("-p", "--priority", min=0, max=4)] = None,
    tier: Annotated[int | None, typer.Option("--tier", min=1, max=4)] = None,
    labels: Annotated[str | None, typer.Option("-l", "--labels")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 50,
    json_output: Annotated[
        bool, typer.Option("--json", help="Output raw JSON for programmatic use")
    ] = False,
) -> None:
    """List tasks with optional filters.

    Examples:
        st list --status pending
        st list -t bug -p 1
        st list --tier 1
        st list --labels "complexity:small"
        st list --type refactor --json | jq '.tasks[0].id'
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

    if json_output:
        output_json({"tasks": result["tasks"], "total": len(result["tasks"])})
    else:
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


def _fetch_triggered_references(task_type: str) -> list[dict[str, Any]]:
    """Fetch task-type triggered references from Agent Hub."""
    import httpx

    from ..config import get_agent_hub_url

    try:
        url = f"{get_agent_hub_url()}/api/memory/triggered-references"
        response = httpx.get(url, params={"task_type": task_type}, timeout=5.0)
        if response.status_code == 200:
            data = response.json()
            return data.get("references", [])
    except Exception:
        pass
    return []


def _fetch_phase_triggered_references(phase: str) -> list[dict[str, Any]]:
    """Fetch phase-triggered references from Agent Hub."""
    import httpx

    from ..config import get_agent_hub_url

    try:
        url = f"{get_agent_hub_url()}/api/memory/phase-triggered-references"
        response = httpx.get(url, params={"phase": phase}, timeout=5.0)
        if response.status_code == 200:
            data = response.json()
            return data.get("references", [])
    except Exception:
        pass
    return []


@app.command()
def context(
    task_id: Annotated[str, typer.Argument(help="Task ID (required)")],
    subtask: Annotated[
        str | None,
        typer.Option("--subtask", "-s", help="Subtask ID for scoped context (e.g., 1.1)"),
    ] = None,
) -> None:
    """Get task or subtask context in a single call.

    Full task context (default):
        Returns task details, all subtasks with steps, decisions, blockers,
        and task-type triggered references from memory.

    Subtask-scoped context (--subtask X.Y):
        Returns task summary (objective, spirit, done_when), subtask details
        with steps, subtask dependencies with status, and phase-triggered
        references from memory.

    This is THE command for agents to get task/subtask information.

    Examples:
        st context task-abc123                  # Full task context
        st context task-abc123 --subtask 1.1   # Subtask-scoped context
    """
    from ..output import output_subtask_context

    client = STClient(require_project=False)

    try:
        # Fetch task
        task = client.get_task(task_id)

        # Fetch task_spirit for normalized fields (plan_status, context, etc.)
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
            phase_refs = _fetch_phase_triggered_references(phase) if phase else []

            output_subtask_context(task, target_subtask, dep_status, phase_refs)
        else:
            # Full task context
            # Fetch blockers
            deps = client.list_dependencies(task_id)
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

            # Fetch task-type triggered references
            task_type = task.get("task_type", "")
            task_refs = _fetch_triggered_references(task_type) if task_type else []

            output_context(task, subtasks, blockers, task_refs)

        # Show worktree info if available
        worktree_info = get_worktree_info(task_id)
        if worktree_info:
            worktree_path = str(worktree_info.path)
            # Use ~ shorthand for home directory
            home = str(Path.home())
            display_path = worktree_path.replace(home, "~")
            typer.echo("")
            typer.echo(f"WORKTREE: {display_path}")
            typer.echo(f"  branch: {worktree_info.branch}")
            typer.echo(f"  cd {display_path}  # to work in isolation")

    except APIError as e:
        handle_api_error(e)
        return


@app.command()
def export(
    task_id: Annotated[str, typer.Argument(help="Task ID (required)")],
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
        criteria: list[dict[str, Any]] = []

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
def cancel(
    task_id: Annotated[str | None, typer.Argument()] = None,
    reason: Annotated[str, typer.Option("-r", "--reason")] = "",
) -> None:
    """Cancel a task (mark as cancelled from any state).

    Use this for tasks that are invalid, obsolete, or no longer needed.
    Works from any non-terminal state (pending, running, paused, failed).

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st cancel task-abc123 -r "Invalid: file doesn't exist"
        st cancel -r "Obsolete: already fixed"    # Uses active context
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
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
def delete(
    task_id: Annotated[str | None, typer.Argument()] = None,
) -> None:
    """Delete a task.

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st delete task-abc123
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)

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

    data: dict[str, Any] = {
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
def log(
    message: str,
    task_id: Annotated[str | None, typer.Option("-t", "--task", help="Task ID")] = None,
) -> None:
    """Append a log entry to a task's progress log.

    A timestamp is automatically prepended to the message.

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st log "Started working on feature"           # Uses active context
        st log "Fixed issue" --task task-abc123       # Explicit task
    """
    from datetime import datetime

    from ..context import require_task_id

    task_id = require_task_id(task_id)
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

    # Validate step structure: every subtask must have steps with verify_command and expected_output
    for subtask in subtasks:
        subtask_id = subtask.get("id", "?")
        steps = subtask.get("steps", [])

        if not steps:
            issues.append(f"subtask {subtask_id}: missing required 'steps' array")
            continue

        for step_idx, step in enumerate(steps):
            step_num = step_idx + 1
            # Steps can be strings (legacy) or objects with verify_command
            if isinstance(step, str):
                issues.append(
                    f"subtask {subtask_id} step {step_num}: must be object with verify_command, "
                    f"not string"
                )
                continue

            if not step.get("verify_command"):
                issues.append(
                    f"subtask {subtask_id} step {step_num}: missing required 'verify_command'"
                )
            if not step.get("expected_output"):
                issues.append(
                    f"subtask {subtask_id} step {step_num}: missing required 'expected_output'"
                )

    # Validate deploy and browser steps for backend/frontend subtasks
    for subtask in subtasks:
        subtask_id = subtask.get("id", "?")
        phase = subtask.get("phase", "").lower()
        steps = subtask.get("steps", [])

        if phase in ("backend", "frontend") and steps:
            has_deploy = False
            has_browser_check = False

            for step in steps:
                if isinstance(step, dict):
                    step_desc = step.get("description", "").lower()
                    verify_cmd = step.get("verify_command", "").lower()

                    if "deploy" in step_desc or "rebuild.sh" in verify_cmd:
                        has_deploy = True
                    if "agent-browser" in verify_cmd or "console error" in step_desc:
                        has_browser_check = True

            if not has_deploy:
                issues.append(
                    f"subtask {subtask_id} (phase={phase}): must have deploy step "
                    f"(rebuild.sh in verify_command or 'deploy' in description)"
                )

            # Frontend subtasks also require browser verification
            if phase == "frontend" and not has_browser_check:
                issues.append(
                    f"subtask {subtask_id} (phase=frontend): must have browser verification step "
                    f"(agent-browser in verify_command or 'console error' in description)"
                )

    # Validate final verification subtask: last subtask must be verification phase
    if subtasks:
        last_subtask = subtasks[-1]
        last_id = last_subtask.get("id", "?")
        last_phase = last_subtask.get("phase", "").lower()
        last_desc = last_subtask.get("description", "").lower()

        is_verification = (
            last_phase == "verification" or "verification" in last_desc or "verify" in last_desc
        )
        if not is_verification:
            issues.append(
                f"Final subtask {last_id} must be a verification subtask "
                f"(phase='verification' or description contains 'verification')"
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
    task_id: Annotated[str | None, typer.Argument()] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Validate only, don't execute"),
    ] = False,
    at: Annotated[
        str | None,
        typer.Option(
            "--at",
            help="Schedule for later: '22:00', '2025-02-01 22:00', 'in 30m', 'in 2h'",
        ),
    ] = None,
) -> None:
    """Queue task for autonomous execution via Celery.

    Executes the full autonomous pipeline:
    - Pristine codebase check (dt --check)
    - Worktree isolation per task
    - Multi-subtask execution with fresh context
    - Step verification via verify_command
    - 3-2-1 escalation (worker → supervisor → human)
    - AI review and auto-merge

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st autocode task-abc123              # Queue for immediate execution
        st autocode --dry-run                # Validate without executing
        st autocode task-abc --at "22:00"    # Schedule for 10pm today/tomorrow
        st autocode task-abc --at "in 2h"    # Schedule for 2 hours from now
    """
    from app.scheduling import OnceSchedule, get_dispatcher
    from app.scheduling.types import parse_at_time

    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        task = client.get_task(task_id)
        subtasks_response = client.get_subtasks(task_id)
        subtasks = subtasks_response.get("subtasks", [])
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    if not subtasks:
        output_error(f"Task {task_id} has no subtasks. Run /plan_it first.")
        raise typer.Exit(1)

    current_status = task.get("status", "pending")
    if current_status in ("running", "queue"):
        output_error(f"Task {task_id} is already {current_status}.")
        raise typer.Exit(1)
    if current_status in ("completed", "merged", "pr_created"):
        output_error(f"Task {task_id} is already {current_status}.")
        raise typer.Exit(1)

    schedule = None
    if at:
        try:
            scheduled_time = parse_at_time(at)
            schedule = OnceSchedule(timestamp=scheduled_time)
        except ValueError as e:
            output_error(f"Invalid --at value: {e}")
            raise typer.Exit(1) from None

    if dry_run:
        incomplete = [s for s in subtasks if not s.get("passes")]
        result = {
            "task_id": task_id,
            "status": "dry_run",
            "subtasks_total": len(subtasks),
            "subtasks_incomplete": len(incomplete),
            "next_subtask": incomplete[0]["subtask_id"] if incomplete else None,
            "message": f"Would queue {task_id} for autonomous execution",
        }
        if schedule:
            result["scheduled_for"] = schedule.timestamp.isoformat()
        output_json(result)
        return

    try:
        client.update_status(task_id, status="queue")
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    project_id = task.get("project_id", "summitflow")
    dispatcher = get_dispatcher()
    published = dispatcher.publish_task_ready(task_id, project_id, schedule)

    if schedule:
        output_json(
            {
                "task_id": task_id,
                "status": "scheduled",
                "scheduled_for": schedule.timestamp.isoformat(),
                "message": f"Task scheduled for {schedule.timestamp.strftime('%Y-%m-%d %H:%M UTC')}",
            }
        )
    elif published:
        output_json(
            {
                "task_id": task_id,
                "status": "queued",
                "dispatch": "immediate",
                "message": f"Task queued for immediate execution. Monitor via: st context {task_id}",
            }
        )
    else:
        output_json(
            {
                "task_id": task_id,
                "status": "queued",
                "dispatch": "fallback",
                "message": f"Task queued (Redis unavailable, will be picked up by Beat). Monitor via: st context {task_id}",
            }
        )


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

    # Validate step structure and final verification subtask (same as verify_plan)
    subtasks = plan.get("subtasks", [])
    issues: list[str] = []

    for subtask in subtasks:
        subtask_id = subtask.get("id", "?")
        steps = subtask.get("steps", [])

        if not steps:
            issues.append(f"subtask {subtask_id}: missing required 'steps' array")
            continue

        for step_idx, step in enumerate(steps):
            step_num = step_idx + 1
            if isinstance(step, str):
                issues.append(
                    f"subtask {subtask_id} step {step_num}: must be object with verify_command"
                )
                continue

            if not step.get("verify_command"):
                issues.append(
                    f"subtask {subtask_id} step {step_num}: missing required 'verify_command'"
                )
            if not step.get("expected_output"):
                issues.append(
                    f"subtask {subtask_id} step {step_num}: missing required 'expected_output'"
                )

    # Validate deploy and browser steps for backend/frontend subtasks
    for subtask in subtasks:
        subtask_id = subtask.get("id", "?")
        phase = subtask.get("phase", "").lower()
        steps = subtask.get("steps", [])

        if phase in ("backend", "frontend") and steps:
            has_deploy = False
            has_browser_check = False

            for step in steps:
                if isinstance(step, dict):
                    step_desc = step.get("description", "").lower()
                    verify_cmd = step.get("verify_command", "").lower()

                    if "deploy" in step_desc or "rebuild.sh" in verify_cmd:
                        has_deploy = True
                    if "agent-browser" in verify_cmd or "console error" in step_desc:
                        has_browser_check = True

            if not has_deploy:
                issues.append(
                    f"subtask {subtask_id} (phase={phase}): must have deploy step "
                    f"(rebuild.sh in verify_command or 'deploy' in description)"
                )

            # Frontend subtasks also require browser verification
            if phase == "frontend" and not has_browser_check:
                issues.append(
                    f"subtask {subtask_id} (phase=frontend): must have browser verification step "
                    f"(agent-browser in verify_command or 'console error' in description)"
                )

    # Validate final verification subtask
    if subtasks:
        last_subtask = subtasks[-1]
        last_id = last_subtask.get("id", "?")
        last_phase = last_subtask.get("phase", "").lower()
        last_desc = last_subtask.get("description", "").lower()

        is_verification = (
            last_phase == "verification" or "verification" in last_desc or "verify" in last_desc
        )
        if not is_verification:
            issues.append(
                f"Final subtask {last_id} must be a verification subtask "
                f"(phase='verification' or description contains 'verification')"
            )

    if issues:
        output_error("FAIL: Step structure validation failed")
        for issue in issues:
            typer.echo(f"  - {issue}", err=True)
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
            # Will print summary after task_spirit write

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
        # Will print summary after task_spirit write

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
        typer.echo(f"WARN task_spirit write failed: {e}", err=True)

    # Final TOON summary
    typer.echo(f"IMPORT:{task_id}|{complexity}|{len(subtasks)} subtasks")


# Error stubs for removed commands - provide helpful redirects
@app.command("work", hidden=True)
def work_removed() -> None:
    """Removed: use st claim + st context instead."""
    typer.echo("Command 'work' has been removed.\n", err=True)
    typer.echo("Use instead:", err=True)
    typer.echo("  st claim <id>    - Start work (creates checkpoint)", err=True)
    typer.echo("  st context <id>  - Get task/subtask details", err=True)
    raise typer.Exit(1)


@app.command("show", hidden=True)
def show_removed() -> None:
    """Removed: use st context instead."""
    typer.echo("Command 'show' has been removed.\n", err=True)
    typer.echo("Use instead:", err=True)
    typer.echo("  st context <task-id>                  - Full task context", err=True)
    typer.echo("  st context <task-id> --subtask X.Y    - Subtask-scoped context", err=True)
    raise typer.Exit(1)


@app.command("close", hidden=True)
def close_removed() -> None:
    """Removed: use st done instead."""
    typer.echo("Command 'close' has been removed.\n", err=True)
    typer.echo("Use instead:", err=True)
    typer.echo(
        "  st done <id>     - Complete task (verifies, merges, removes checkpoint)", err=True
    )
    raise typer.Exit(1)


@app.command("update", hidden=True)
def update_removed() -> None:
    """Removed: use lifecycle commands instead."""
    typer.echo("Command 'update' has been removed.\n", err=True)
    typer.echo("Use lifecycle commands instead:", err=True)
    typer.echo("  st claim <id>    - Start work (creates checkpoint)", err=True)
    typer.echo("  st done <id>     - Complete work (merges, removes checkpoint)", err=True)
    typer.echo("  st abandon <id>  - Rollback work (restores checkpoint)", err=True)
    raise typer.Exit(1)
