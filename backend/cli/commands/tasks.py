"""Task commands for the CLI."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ..client import APIError, STClient
from ..lib.usage import usage
from ..output import set_compact_output
from .task_plan_contract import (
    CREATE_COMMAND_HELP,
    FROM_FILE_OPTION_HELP,
    PLAN_OPTION_HELP,
    VERIFY_COMMAND_HELP,
    VERIFY_FILE_ARGUMENT_HELP,
)
from .tasks_helpers import (
    resolve_log_inputs as _resolve_log_inputs,
)

app = typer.Typer(help="Task management commands")

_DEFAULT_TASK_TYPE = "task"
_DEFAULT_CRITIQUE_STAGE = "task_shape"
_DEFAULT_CRITIQUE_AGENT = "specifier"


@app.command(help=CREATE_COMMAND_HELP)
@usage(
    surface="st.create",
    cmd='st create "title"',
    when="create a task; project auto-detected from cwd",
    precautions=(
        "bare title triggers auto-enrichment; pass --draft for kernel-only intake",
        "--plan plan.md for pre-validated structured plans",
        "--type bug|idea for typed kernels",
    ),
    tier="mandate",
)
def create(
    title: Annotated[str | None, typer.Argument()] = None,
    from_file: Annotated[
        Path | None,
        typer.Option("--from-file", help=FROM_FILE_OPTION_HELP),
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    draft: Annotated[
        bool,
        typer.Option("--draft", help="Create kernel only; skip auto-enrichment pipeline."),
    ] = False,
    description: Annotated[str | None, typer.Option("-d", "--description")] = None,
    priority: Annotated[int, typer.Option("-p", "--priority", min=0, max=4)] = 2,
    labels: Annotated[str | None, typer.Option("-l", "--labels")] = None,
    task_type: Annotated[
        str,
        typer.Option("-t", "--type", help="Task type: task, bug, idea, refactor, ..."),
    ] = _DEFAULT_TASK_TYPE,
    parent: Annotated[str | None, typer.Option("--parent")] = None,
    plan: Annotated[
        Path | None,
        typer.Option("--plan", help=PLAN_OPTION_HELP),
    ] = None,
    task_id: Annotated[str | None, typer.Option("--task")] = None,
    blocked_by: Annotated[str | None, typer.Option("--blocked-by")] = None,
    execution_mode: Annotated[str | None, typer.Option("--execution-mode", hidden=True)] = None,
    manual_only: Annotated[bool, typer.Option("--manual-only", hidden=True)] = False,
    autonomous: Annotated[
        bool,
        typer.Option("--autonomous", help="Shorthand for --execution-mode autonomous."),
    ] = False,
) -> None:
    from .tasks_create import create_task_command

    create_task_command(
        title, from_file, dry_run, description, priority, labels,
        task_type, parent, plan, blocked_by, execution_mode, manual_only, autonomous,
        draft=draft, task_id=task_id,
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
@usage(
    surface="st.ready",
    cmd="st ready --limit N",
    when="find next claimable task in the current project (cwd auto-detected)",
    precautions=(
        "blockers render inline as {id} (status, type); no follow-up context call needed",
        "use st ready-all for cross-project overview",
    ),
    tier="mandate",
)
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
@usage(
    surface="st.context",
    cmd="st context <task-id>",
    when="after st claim, before editing — get full task brief + plan + history",
    precautions=(
        "claim first; reading context without claiming risks duplicate work",
        "use --subtask X.Y for subtask context inside a task",
    ),
    tier="mandate",
)
def context(
    task_id: Annotated[str, typer.Argument()],
    subtask: Annotated[str | None, typer.Option("--subtask", "-s")] = None,
    compact: Annotated[bool | None, typer.Option("--compact/--no-compact")] = None,
) -> None:
    """Get task or subtask context in a single call."""
    _context_command(task_id, subtask, compact)


def _context_command(task_id: str, subtask: str | None, compact: bool | None) -> None:
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
@usage(
    surface="st.cancel",
    cmd='st cancel <task-id> -r "reason"',
    when="task is no longer valid (out of scope, superseded, won't-do); preserves history",
    precautions=(
        "cancel preserves the task record; use st abandon to discard work-in-progress instead",
        "always provide -r reason for audit trail",
    ),
    tier="reference",
)
def cancel(
    task_id: Annotated[str | None, typer.Argument()] = None,
    reason: Annotated[str, typer.Option("-r", "--reason")] = "",
) -> None:
    """Cancel a task (mark as cancelled from any state)."""
    from .tasks_lifecycle import cancel_task_command

    cancel_task_command(task_id, reason)


@app.command()
@usage(
    surface="st.pause",
    cmd='st pause <task-id> -r "reason"',
    when="stop work but plan to return; releases claim so others can pick up",
    precautions=(
        "commit/push work-in-progress before pausing; pause does not preserve dirty state",
        "use st reopen to return; reopen accepts any non-pending state",
    ),
    tier="reference",
)
def pause(
    task_id: Annotated[str | None, typer.Argument()] = None,
    reason: Annotated[str, typer.Option("-r", "--reason")] = "",
) -> None:
    """Pause a task and release its active claim."""
    from .tasks_lifecycle import pause_task_command

    pause_task_command(task_id, reason)


@app.command()
@usage(
    surface="st.reopen",
    cmd='st reopen <task-id> -r "reason"',
    when="return a paused/completed/cancelled task to the ready queue",
    precautions=("must st claim again after reopen; reopen only moves to pending",),
    tier="reference",
)
def reopen(
    task_id: Annotated[str | None, typer.Argument()] = None,
    reason: Annotated[str, typer.Option("-r", "--reason")] = "",
) -> None:
    """Reopen a task (move it back to pending). Accepts any non-pending state."""
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
@usage(
    surface="st.update",
    cmd='st update <task-id> --title "..." --priority 1',
    when="fix in-flight task fields (title, priority, labels, description, plan); not for lifecycle changes",
    precautions=(
        "--plan swaps the spirit plan content and resets plan_status to draft",
        "use st cancel/pause/reopen/abandon for status transitions, not st update",
    ),
    tier="reference",
)
def update(
    task_id: Annotated[str, typer.Argument()],
    title: Annotated[str | None, typer.Option("--title")] = None,
    priority: Annotated[int | None, typer.Option("--priority", min=0, max=4)] = None,
    labels: Annotated[str | None, typer.Option("--labels", help="Comma-separated label list")] = None,
    description: Annotated[str | None, typer.Option("--description", "-d")] = None,
    plan: Annotated[Path | None, typer.Option("--plan", help="Swap the task plan from a plan.json")] = None,
) -> None:
    """Update in-flight task fields."""
    from .tasks_lifecycle import update_task_command

    update_task_command(task_id, title=title, priority=priority, labels=labels,
                        description=description, plan=plan)


@app.command()
@usage(
    surface="st.log",
    cmd='st log <task-id> "progress note"',
    when="record progress, decisions, or blockers on a claimed task",
    precautions=("prefer task-id first form; trailing task-id is a legacy alias",),
    tier="reference",
)
def log(
    arg1: Annotated[str, typer.Argument(help="Task ID or message")],
    arg2: Annotated[str | None, typer.Argument(help="Message or legacy trailing task ID")] = None,
    task_id: Annotated[str | None, typer.Option("-t", "--task", help="Task ID")] = None,
    message: Annotated[str | None, typer.Option("-m", "--message", help="Progress note")] = None,
) -> None:
    """Append a task log entry. Prefer `st log <task-id> "<message>"`."""
    from .tasks_commands import append_task_log

    resolved_message, resolved_task_id = _resolve_log_inputs(arg1, arg2, task_id, message)
    append_task_log(resolved_message, resolved_task_id, STClient())


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


@app.command("verify", help=VERIFY_COMMAND_HELP)
def verify_plan(
    file_path: Annotated[Path, typer.Argument(help=VERIFY_FILE_ARGUMENT_HELP)],
) -> None:
    from .tasks_verify import verify_plan_file

    verify_plan_file(file_path, STClient(require_project=False))


@app.command()
def autocode(
    task_id: Annotated[str | None, typer.Argument()] = None,
    next_task: Annotated[
        bool,
        typer.Option("--next", help="Queue the first execution-ready task from this project's ready queue."),
    ] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    at: Annotated[str | None, typer.Option("--at")] = None,
) -> None:
    """Queue task for autonomous execution via Hatchet."""
    from .tasks_autocode import autocode_task

    autocode_task(task_id, dry_run, at, STClient(require_project=False), next_task=next_task)


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
