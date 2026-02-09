"""Task commands for the CLI."""

from __future__ import annotations

import json
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
from .tasks_import import create_from_file, import_plan_file

app = typer.Typer(help="Task management commands")


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
    from .tasks_ready import list_ready_tasks

    client = STClient()
    try:
        list_ready_tasks(limit, blocked, client)
    except APIError:
        return


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
    from .tasks_context import get_task_context

    client = STClient(require_project=False)
    get_task_context(task_id, subtask, client)


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
    from .tasks_commands import export_task

    client = STClient(require_project=False)
    export_task(task_id, output, client)


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
    from .tasks_commands import create_bug_task

    client = STClient()
    create_bug_task(title, description, priority, labels, from_task, client)


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
    from ..context import require_task_id
    from .tasks_commands import append_task_log

    task_id = require_task_id(task_id)
    client = STClient()
    append_task_log(message, task_id, client)


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
    from .tasks_verify import verify_plan_file

    client = STClient(require_project=False)
    verify_plan_file(file_path, client)


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
    """Queue task for autonomous execution via Hatchet.

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
    from ..context import require_task_id
    from .tasks_commands import autocode_task

    task_id = require_task_id(task_id)
    client = STClient(require_project=False)
    autocode_task(task_id, dry_run, at, client)


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
    client = STClient()
    task, task_id = import_plan_file(file_path, dry_run, task_id, client)

    # Final TOON summary
    complexity = task.get("complexity", "SIMPLE")
    subtask_count = len(task.get("subtasks", []))
    typer.echo(f"IMPORT:{task_id}|{complexity}|{subtask_count} subtasks")


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
