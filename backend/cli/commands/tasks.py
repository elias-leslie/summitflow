"""Task commands for the CLI."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import set_compact_output

app = typer.Typer(help="Task management commands")

# Magic string constants
_DEFAULT_TASK_TYPE = "task"
_IDEA_LABELS = "crowdsourced"
_IDEA_EXECUTION_MODE = "autonomous"
_DEFAULT_CRITIQUE_STAGE = "task_shape"
_DEFAULT_CRITIQUE_AGENT = "specifier"


def _removed_command(name: str, replacement: str) -> None:
    """Emit a standard error for removed commands and exit."""
    typer.echo(f"Error: '{name}' removed. Use '{replacement}'", err=True)
    raise typer.Exit(1)


@app.command()
def create(
    title: Annotated[str | None, typer.Argument()] = None,
    from_file: Annotated[Path | None, typer.Option("--from-file")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    description: Annotated[str | None, typer.Option("-d", "--description")] = None,
    priority: Annotated[int, typer.Option("-p", "--priority", min=0, max=4)] = 2,
    labels: Annotated[str | None, typer.Option("-l", "--labels")] = None,
    task_type: Annotated[str, typer.Option("-t", "--type")] = _DEFAULT_TASK_TYPE,
    parent: Annotated[str | None, typer.Option("--parent")] = None,
    plan: Annotated[Path | None, typer.Option("--plan")] = None,
    task_id: Annotated[str | None, typer.Option("--task")] = None,
    blocked_by: Annotated[str | None, typer.Option("--blocked-by")] = None,
    execution_mode: Annotated[str | None, typer.Option("--execution-mode")] = None,
    manual_only: Annotated[bool, typer.Option("--manual-only")] = False,
    autonomous: Annotated[bool, typer.Option("--autonomous")] = False,
) -> None:
    """Create a new task or batch create from file."""
    from .tasks_create import create_task_command

    create_task_command(
        title, from_file, dry_run, description, priority, labels,
        task_type, parent, plan, blocked_by, execution_mode, manual_only, autonomous, task_id
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
    compact: Annotated[bool | None, typer.Option("--compact/--no-compact")] = None,
) -> None:
    """List tasks with optional filters."""
    from .tasks_list import list_tasks_command

    if compact is not None:
        set_compact_output(compact)
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


@app.command("ready-all")
def ready_all(
    limit: Annotated[int, typer.Option("--limit", help="Top tasks per project")] = 3,
) -> None:
    """Cross-project summary: ready and blocked tasks across all projects.

    Shows per-project counts with top tasks prioritized by:
    blocked first, then bugs, then by priority level.

    Examples:
        st ready-all
        st ready-all --limit 5
    """
    from .tasks_ready_all import list_ready_all

    try:
        list_ready_all(limit, STClient(require_project=False))
    except APIError:
        return


@app.command()
def context(
    task_id: Annotated[str, typer.Argument()],
    subtask: Annotated[str | None, typer.Option("--subtask", "-s")] = None,
    compact: Annotated[bool | None, typer.Option("--compact/--no-compact")] = None,
) -> None:
    """Get task or subtask context in a single call."""
    from .tasks_context import get_task_context

    if compact is not None:
        set_compact_output(compact)
    get_task_context(task_id, subtask, STClient(require_project=False))


@app.command()
def export(
    task_id: Annotated[str, typer.Argument()],
    output: Annotated[str | None, typer.Option("-o", "--output")] = None,
) -> None:
    """Export complete task details to JSON file."""
    from .tasks_export import export_task

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
def reopen(
    task_id: Annotated[str | None, typer.Argument()] = None,
    reason: Annotated[str, typer.Option("-r", "--reason")] = "",
) -> None:
    """Reopen a task (move it back to pending)."""
    from .tasks_lifecycle import reopen_task_command

    reopen_task_command(task_id, reason)


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
    """Create a bug task (shorthand for create -t bug).

    Requires explicit project: st -P <project> bug "title"
    """
    from ..config import get_config
    from ..output import require_explicit_project
    from .tasks_bug import create_bug_task

    require_explicit_project(get_config())
    create_bug_task(title, description, priority, labels, from_task, STClient())


@app.command()
def log(
    message: str,
    task_id_arg: Annotated[str | None, typer.Argument(help="Task ID (optional trailing form)")] = None,
    task_id: Annotated[str | None, typer.Option("-t", "--task", help="Task ID")] = None,
) -> None:
    """Append a log entry to a task's progress log."""
    from .tasks_commands import append_task_log

    resolved_task_id = task_id or task_id_arg
    if not resolved_task_id:
        typer.echo("Error: task id required via trailing argument or --task", err=True)
        raise typer.Exit(1)
    append_task_log(message, resolved_task_id, STClient())


@app.command("sync-progress")
def sync_progress(
    task_id: Annotated[str | None, typer.Argument()] = None,
    acknowledge_none: Annotated[
        bool,
        typer.Option("--none", help="Acknowledge no memories for synced subtasks"),
    ] = False,
) -> None:
    """Sync subtask pass state from already-completed steps."""
    from .tasks_progress import sync_progress_command

    sync_progress_command(task_id, acknowledge_none)


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

    Requires explicit project (-P flag or ST_PROJECT_ID env var).
    Shorthand for: st create "..." --labels crowdsourced --autonomous

    Examples:
        st -P summitflow idea "Add dark mode support"
        st -P summitflow idea "Refactor auth module to use JWT" -p 1
    """
    from .tasks_create import create_task_command

    create_task_command(
        title=description,
        from_file=None,
        dry_run=False,
        description=None,
        priority=priority,
        labels=_IDEA_LABELS,
        task_type=_DEFAULT_TASK_TYPE,
        parent=None,
        plan=None,
        blocked_by=None,
        execution_mode=_IDEA_EXECUTION_MODE,
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
    from .tasks_autocode import autocode_task

    autocode_task(require_task_id(task_id), dry_run, at, STClient(require_project=False))


@app.command("critique")
def critique(
    task_id: Annotated[str, typer.Argument()],
    stage: Annotated[
        str,
        typer.Option("--stage", help="Critique stage: task_shape, pre_close, or both"),
    ] = _DEFAULT_CRITIQUE_STAGE,
    agent: Annotated[
        str,
        typer.Option("--agent", help="Agent Hub agent slug to use for the critique"),
    ] = _DEFAULT_CRITIQUE_AGENT,
    force: Annotated[
        bool,
        typer.Option("--force", help="Run even when the task does not currently require a second opinion"),
    ] = False,
) -> None:
    """Request and store a second-opinion critique for a task."""
    from .tasks_critique import critique_task_command

    critique_task_command(task_id, stage, agent, force)


# Register stubs for removed commands so old scripts get a clear error.
# Uses a loop to avoid one named function per removed command.
_REMOVED: list[tuple[str, str]] = [
    ("import", "st create --plan plan.json"),
    ("work", "st claim <id>' and 'st context <id>"),
    ("show", "st context <task-id>"),
    ("close", "st done <id>"),
    ("update", "st claim/done/abandon"),
]
for _cmd, _replacement in _REMOVED:

    def _make_stub(
        args: Annotated[list[str] | None, typer.Argument(hidden=True)] = None,
        *,
        name: str = _cmd,
        repl: str = _replacement,
    ) -> None:
        hint = repl
        if args:
            # Substitute placeholder with the provided positional arg
            task_id = args[0]
            hint = repl.replace("<task-id>", task_id).replace("<id>", task_id)
        _removed_command(name, hint)

    _make_stub.__doc__ = f"Removed: use {_replacement} instead."
    app.command(_cmd, hidden=True)(_make_stub)
