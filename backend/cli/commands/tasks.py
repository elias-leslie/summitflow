"""Task commands for the CLI."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ..client import APIError, STClient

app = typer.Typer(help="Task management commands")


@app.command()
def create(
    title: Annotated[str | None, typer.Argument()] = None,
    from_file: Annotated[Path | None, typer.Option("--from-file")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    description: Annotated[str | None, typer.Option("-d", "--description")] = None,
    priority: Annotated[int, typer.Option("-p", "--priority", min=0, max=4)] = 2,
    labels: Annotated[str | None, typer.Option("-l", "--labels")] = None,
    task_type: Annotated[str, typer.Option("-t", "--type")] = "task",
    parent: Annotated[str | None, typer.Option("--parent")] = None,
    plan: Annotated[str | None, typer.Option("--plan")] = None,
    blocked_by: Annotated[str | None, typer.Option("--blocked-by")] = None,
    autonomous: Annotated[bool, typer.Option("--autonomous")] = False,
) -> None:
    """Create a new task or batch create from file."""
    from .tasks_create import create_task_command

    create_task_command(
        title, from_file, dry_run, description, priority, labels,
        task_type, parent, plan, blocked_by, autonomous
    )


@app.command("list")
def list_tasks(
    status: Annotated[str | None, typer.Option("-s", "--status")] = None,
    task_type: Annotated[str | None, typer.Option("-t", "--type")] = None,
    priority: Annotated[int | None, typer.Option("-p", "--priority", min=0, max=4)] = None,
    tier: Annotated[int | None, typer.Option("--tier", min=1, max=4)] = None,
    labels: Annotated[str | None, typer.Option("-l", "--labels")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 50,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List tasks with optional filters."""
    from .tasks_list import list_tasks_command

    list_tasks_command(status, task_type, priority, tier, labels, limit, json_output)


@app.command()
def ready(
    limit: Annotated[int, typer.Option("--limit")] = 50,
    blocked: Annotated[bool, typer.Option("--blocked")] = False,
) -> None:
    """List tasks ready to work on (not blocked)."""
    from .tasks_ready import list_ready_tasks

    try:
        list_ready_tasks(limit, blocked, STClient())
    except APIError:
        return


@app.command()
def context(
    task_id: Annotated[str, typer.Argument()],
    subtask: Annotated[str | None, typer.Option("--subtask", "-s")] = None,
) -> None:
    """Get task or subtask context in a single call."""
    from .tasks_context import get_task_context

    get_task_context(task_id, subtask, STClient(require_project=False))


@app.command()
def export(
    task_id: Annotated[str, typer.Argument()],
    output: Annotated[str | None, typer.Option("-o", "--output")] = None,
) -> None:
    """Export complete task details to JSON file."""
    from .tasks_commands import export_task

    export_task(task_id, output, STClient(require_project=False))


@app.command()
def cancel(
    task_id: Annotated[str | None, typer.Argument()] = None,
    reason: Annotated[str, typer.Option("-r", "--reason")] = "",
) -> None:
    """Cancel a task (mark as cancelled from any state)."""
    from .tasks_lifecycle import cancel_task_command

    cancel_task_command(task_id, reason)


@app.command()
def delete(
    task_id: Annotated[str | None, typer.Argument()] = None,
) -> None:
    """Delete a task."""
    from .tasks_lifecycle import delete_task_command

    delete_task_command(task_id)


@app.command()
def bug(
    title: str,
    description: Annotated[str | None, typer.Option("-d", "--description")] = None,
    priority: Annotated[int, typer.Option("-p", "--priority", min=0, max=4)] = 2,
    labels: Annotated[str | None, typer.Option("-l", "--labels")] = None,
    from_task: Annotated[str | None, typer.Option("--from")] = None,
) -> None:
    """Create a bug task (shorthand for create -t bug)."""
    from .tasks_commands import create_bug_task

    create_bug_task(title, description, priority, labels, from_task, STClient())


@app.command()
def log(
    message: str,
    task_id: Annotated[str | None, typer.Option("-t", "--task", help="Task ID")] = None,
) -> None:
    """Append a log entry to a task's progress log."""
    from ..context import require_task_id
    from .tasks_commands import append_task_log

    append_task_log(message, require_task_id(task_id), STClient())


@app.command("verify")
def verify_plan(
    file_path: Annotated[Path, typer.Argument()],
) -> None:
    """Verify a plan.json file against the schema."""
    from .tasks_verify import verify_plan_file

    verify_plan_file(file_path, STClient(require_project=False))


@app.command()
def idea(
    description: Annotated[str, typer.Argument()],
    priority: Annotated[int, typer.Option("-p", "--priority", min=0, max=4)] = 3,
) -> None:
    """Submit an idea for autonomous ideation and execution.

    Shorthand for: st create "..." --labels crowdsourced --autonomous

    Examples:
        st idea "Add dark mode support"
        st idea "Refactor auth module to use JWT" -p 1
    """
    from .tasks_create import create_task_command

    create_task_command(
        title=description,
        from_file=None,
        dry_run=False,
        description=None,
        priority=priority,
        labels="crowdsourced",
        task_type="task",
        parent=None,
        plan=None,
        blocked_by=None,
        autonomous=True,
    )


@app.command()
def autocode(
    task_id: Annotated[str | None, typer.Argument()] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    at: Annotated[str | None, typer.Option("--at")] = None,
) -> None:
    """Queue task for autonomous execution via Hatchet."""
    from ..context import require_task_id
    from .tasks_commands import autocode_task

    autocode_task(require_task_id(task_id), dry_run, at, STClient(require_project=False))


@app.command("import")
def import_plan(
    file_path: Annotated[Path, typer.Argument()],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Import a plan.json file as a SummitFlow task."""
    from .tasks_import import import_plan_file

    task, task_id = import_plan_file(file_path, dry_run, task_id, STClient())
    complexity = task.get("complexity", "SIMPLE")
    typer.echo(f"IMPORT:{task_id}|{complexity}|{len(task.get('subtasks', []))} subtasks")


# Error stubs for removed commands
@app.command("work", hidden=True)
def work_removed() -> None:
    """Removed: use st claim + st context instead."""
    typer.echo("Error: 'work' removed. Use 'st claim <id>' and 'st context <id>'", err=True)
    raise typer.Exit(1)


@app.command("show", hidden=True)
def show_removed() -> None:
    """Removed: use st context instead."""
    typer.echo("Error: 'show' removed. Use 'st context <task-id>'", err=True)
    raise typer.Exit(1)


@app.command("close", hidden=True)
def close_removed() -> None:
    """Removed: use st done instead."""
    typer.echo("Error: 'close' removed. Use 'st done <id>'", err=True)
    raise typer.Exit(1)


@app.command("update", hidden=True)
def update_removed() -> None:
    """Removed: use lifecycle commands instead."""
    typer.echo("Error: 'update' removed. Use 'st claim/done/abandon'", err=True)
    raise typer.Exit(1)
