"""SummitFlow Tasks CLI entry point."""

import atexit
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Annotated

import typer

from app.storage.connection import close_pool
from app.storage.events import log_task_event

from .config import set_project_override
from .lib.commit_workflow import CommitError, commit_repo, current_repo
from .lib.usage import usage
from .output import set_compact_output, set_human_output, set_progress_only
from .output_context import OutputContext

# Ensure connection pool is closed on exit to avoid thread cleanup warnings
atexit.register(close_pool)

CLI_REFERENCE = """ST CLI - SummitFlow Tasks.

Core loop: pulse --gate | ready | create "<title>" | claim <id> | context <id> | done <id>.
Lifecycle: pause <id> | reopen <id> | cancel <id> | update <id> | abandon <id>.
VCS: vcs doctor | vcs reconcile | commit -m MSG [--task T] | jj diff | jj show.
Tools: check | graph | service | runtime | db | browser | web | wiki | sessions | agent | cleanup | logs | ui.
Use `<command> --help` for command-specific syntax."""

SESSION_EVENTS_COMMAND = "session-events"
PROGRESS_COMMAND = "progress"
COMMAND_UNAVAILABLE_ERROR = "ERROR:st command '{command}' unavailable: {exc}"
COMMIT_ERROR_PREFIX = "ERROR:"
SUCCESS_STATUS = "SUCCESS"
BLOCKED_STATUS = "BLOCKED"
COMMIT_EVENT_PREFIX = "st commit"
COMMIT_COMPACT_TEMPLATE = "COMMIT[1]:status={status} pushed={pushed} detail={detail}"
PROGRESS_ALIAS_MESSAGE = (
    "Command 'st progress' does not exist. Did you mean:\n"
    "  st sync-progress <task-id>              Sync objectively complete, step-backed subtasks\n"
    "  st done <subtask-id> -t <task-id>       Mark individual subtask complete"
)
FORWARD_CONTEXT_SETTINGS = {"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []}

OPTIONAL_COMMANDS = (
    "abandon",
    "agent",
    "agents",
    "autonomous",
    "autosnapshot",
    "backup",
    "browser",
    "checkpoints",
    "claim",
    "claude",
    "cleanup",
    "complete",
    "db",
    "deps",
    "design",
    "docker",
    "done",
    "exec_monitor",
    "feedback",
    "git",
    "graph",
    "health",
    "jj",
    "lease",
    "logs",
    "mandates",
    "memory",
    "migrate_branches",
    "models",
    "note",
    "persona",
    "portfolio",
    "projects",
    "prompt",
    "pulse",
    "refactor",
    "runtime",
    "search",
    "selection",
    "service",
    "session_events",
    "sessions",
    "setup",
    "skills",
    "snapshots",
    "subtask",
    "tasks",
    "tests",
    "tools",
    "ui",
    "vcs",
    "vm",
    "web",
    "wiki",
)

SUBCOMMAND_GROUPS = (
    ("dep", "deps"),
    ("design", "design"),
    ("test", "tests"),
    ("subtask", "subtask"),
    ("autonomous", "autonomous"),
    ("claude", "claude"),
    ("sessions", "sessions"),
    ("projects", "projects"),
    ("git", "git"),
    ("graph", "graph"),
    ("jj", "jj"),
    ("vcs", "vcs"),
    ("backup", "backup"),
    ("service", "service"),
    ("runtime", "runtime"),
    ("health", "health"),
    ("logs", "logs"),
    ("memory", "memory"),
    ("models", "models"),
    ("complete", "complete"),
    ("agent", "agent"),
    ("tools", "tools"),
    ("cleanup", "cleanup"),
    ("prompt", "prompt"),
    ("refactor", "refactor"),
    ("feedback", "feedback"),
    ("persona", "persona"),
    ("portfolio", "portfolio"),
    ("agents", "agents"),
    ("docker", "docker"),
    ("setup", "setup"),
    ("vm", "vm"),
    ("wiki", "wiki"),
    ("ui", "ui"),
    ("selection", "selection"),
)

FORWARDED_ROOT_COMMANDS = (
    ("check", "check", "check"),
    ("db", "db", "db"),
    ("browser", "browser", "browser"),
    ("web", "web", "web"),
)

SNAPSHOT_COMMAND_NAMES = {"snap", "snaps", "recover", "rollback", "prune"}
ROOT_TASK_COMMAND_NAMES = {"claim", "done", "abandon"}


class _FailedCommandModule:
    def __init__(self, command: str, exc: Exception) -> None:
        self.command = command
        self.exc = exc
        self.app = typer.Typer(help=f"{command} command unavailable: {exc}")

        @self.app.callback(invoke_without_command=True)
        def _failed_group() -> None:
            self._raise()

    def __getattr__(self, _name: str):
        def _failed_command() -> None:
            self._raise()

        return _failed_command

    def _raise(self) -> None:
        typer.echo(COMMAND_UNAVAILABLE_ERROR.format(command=self.command, exc=self.exc), err=True)
        raise typer.Exit(1)


def _load_command_module(command: str, *, required: bool = False) -> ModuleType | _FailedCommandModule:
    try:
        return import_module(f"{__package__}.commands.{command}")
    except Exception as exc:
        if required:
            raise
        return _FailedCommandModule(command, exc)


def _load_optional_commands() -> dict[str, ModuleType | _FailedCommandModule]:
    return {name: _load_command_module(name) for name in OPTIONAL_COMMANDS}


_COMMANDS = _load_optional_commands()
_COMMANDS["check"] = _load_command_module("check", required=True)


def _register_root_task_commands() -> None:
    for cmd in _COMMANDS["tasks"].app.registered_commands:
        if cmd.callback is not None:
            app.command(name=cmd.name, hidden=cmd.hidden)(cmd.callback)


def _register_subcommand_groups() -> None:
    for command_name, module_name in SUBCOMMAND_GROUPS:
        app.add_typer(_COMMANDS[module_name].app, name=command_name)


def _register_forwarded_root_commands() -> None:
    for command_name, module_name, callback_name in FORWARDED_ROOT_COMMANDS:
        module = _COMMANDS[module_name]
        app.command(
            command_name,
            context_settings=FORWARD_CONTEXT_SETTINGS,
            help=module.app.info.help,
            add_help_option=False,
        )(getattr(module, callback_name))


def _event_detail_parts(result: dict[str, object]) -> list[str]:
    return [
        f"change={result.get('change_id', '')}",
        f"commit={result.get('commit_id') or result.get('sha') or ''}",
        f"bookmark={result.get('bookmark', '')}",
        f"op={result.get('operation_id', '')}",
        f"pushed={str(result.get('pushed', False)).lower()}",
    ]


def _log_commit_event(task_id: str, result: dict[str, object]) -> None:
    detail = " ".join(part for part in _event_detail_parts(result) if not part.endswith("="))
    log_task_event(task_id, f"{COMMIT_EVENT_PREFIX} {detail}")


def _emit_commit_output(ctx: typer.Context, result: dict[str, object]) -> None:
    if ctx.obj.is_compact:
        detail = result.get("commit_id") or result.get("sha") or result.get("reason") or ""
        print(
            COMMIT_COMPACT_TEMPLATE.format(
                status=result["status"],
                pushed=str(result.get("pushed", False)).lower(),
                detail=detail,
            )
        )
        return

    from .output import output_json

    output_json(result)


def _register_named_command(command_group: typer.Typer, command_name: str) -> None:
    for cmd in command_group.registered_commands:
        if cmd.callback is not None and cmd.name == command_name:
            app.command(name=command_name)(cmd.callback)


def _register_snapshot_commands() -> None:
    for cmd in _COMMANDS["snapshots"].app.registered_commands:
        if cmd.callback is not None and cmd.name in SNAPSHOT_COMMAND_NAMES:
            app.command(name=cmd.name, context_settings=cmd.context_settings or {})(cmd.callback)


def _apply_output_context(ctx: typer.Context, *, human: bool, compact: bool, progress_only: bool) -> None:
    ctx.obj = OutputContext(
        human=human and not compact and not progress_only,
        compact=compact or progress_only,
        progress_only=progress_only,
    )
    set_human_output(ctx.obj.human)
    set_compact_output(ctx.obj.compact)
    set_progress_only(ctx.obj.progress_only)

app = typer.Typer(
    name="st",
    help=CLI_REFERENCE,
    no_args_is_help=True,
    rich_markup_mode=None,
)

# Register task commands at root level
_register_root_task_commands()

# Also register task as a subcommand group for `st task verify` / `st task import`
app.add_typer(_COMMANDS["tasks"].app, name="task", hidden=True)

# Register subcommand groups (hidden from main help - reference above is complete)
_register_subcommand_groups()
app.command(SESSION_EVENTS_COMMAND, help="Agent Hub session events (observability)")(
    _COMMANDS["session_events"].show_events
)
app.command("pulse")(_COMMANDS["pulse"].pulse)
app.command("lease")(_COMMANDS["lease"].lease_command)
app.command("migrate-branches")(_COMMANDS["migrate_branches"].migrate_branches_command)
app.command("search")(_COMMANDS["search"].search)
app.command("exec-log")(_COMMANDS["exec_monitor"].exec_log_command)
app.command("mandates")(_COMMANDS["mandates"].mandates)
app.command("note")(_COMMANDS["note"].note)


@app.command("commit")
@usage(
    surface="st.commit",
    cmd='st commit -m "msg" --push',
    when="user-requested work complete; off-task or residue commits; any time the working tree is dirty and a commit point is reached — never leave residue for the next session",
    precautions=(
        "default: commit the ENTIRE working tree with one message — do not pre-audit files, do not propose --paths scoping, do not ask which subset to include",
        "--paths is opt-in ONLY when the user explicitly asks to split a commit; never volunteer it",
        "after publish, trust printed COMMIT summary not local-clean state",
        "commit before destructive ops (abandon, rollback)",
    ),
    tier="mandate",
)
def commit_command(
    ctx: typer.Context,
    message: Annotated[str, typer.Option("--message", "--msg", "-m", help="Required commit/change description.")],
    push: Annotated[bool, typer.Option("--push/--no-push", help="Publish after describing the change.")] = True,
    task_id: Annotated[str, typer.Option("--task", help="Task id for bookmark and audit log.")] = "",
    repo: Annotated[str | None, typer.Option("--repo", "-R", help="Repository path. Defaults to current repo.")] = None,
    skip_checks: Annotated[
        bool,
        typer.Option("--skip-checks", help="Skip local check gate for local-only recovery commits."),
    ] = False,
    bookmark: Annotated[str, typer.Option("--bookmark", help="Explicit jj bookmark to publish.")] = "",
    paths: Annotated[
        list[str] | None,
        typer.Option(
            "--path",
            "--paths",
            help=(
                "Only commit/publish selected path(s); repeat for multiple paths "
                "(--paths a --paths b). Works for jj and plain-Git repos."
            ),
        ),
    ] = None,
) -> None:
    """High-level st-owned commit workflow."""
    try:
        repo_path = current_repo() if repo is None else Path(repo).expanduser().resolve()
        result = commit_repo(
            repo_path,
            message=message,
            task_id=task_id,
            push=push,
            skip_checks=skip_checks,
            bookmark=bookmark,
            paths=tuple(paths or ()),
        )
    except CommitError as exc:
        typer.echo(f"{COMMIT_ERROR_PREFIX}{exc}", err=True)
        raise typer.Exit(1) from None

    if task_id and result.get("status") == SUCCESS_STATUS:
        _log_commit_event(task_id, result)
    _emit_commit_output(ctx, result)
    if result.get("status") == BLOCKED_STATUS:
        raise typer.Exit(2)


_register_forwarded_root_commands()


@app.command(PROGRESS_COMMAND, hidden=True)
def progress_alias(
    task_id: Annotated[str | None, typer.Argument(help="Task ID")] = None,
) -> None:
    """Alias hint: use 'st sync-progress' or 'st subtask pass' instead."""
    typer.echo(PROGRESS_ALIAS_MESSAGE, err=True)
    raise typer.Exit(1)


# Register checkpoint-aware commands (override old claim from tasks.py)
# These are defined with @app.command() in their modules, so access via module.app
_register_named_command(_COMMANDS["claim"].app, "claim")
app.add_typer(_COMMANDS["checkpoints"].app, name="checkpoints")
app.add_typer(_COMMANDS["skills"].app, name="skills")
_register_snapshot_commands()
app.add_typer(_COMMANDS["autosnapshot"].app, name="autosnap", hidden=True)
for command_name in ROOT_TASK_COMMAND_NAMES - {"claim"}:
    _register_named_command(_COMMANDS[command_name].app, command_name)


@app.callback()
def main(
    ctx: typer.Context,
    project: Annotated[
        str | None,
        typer.Option(
            "-P",
            "--project",
            help="Project ID (overrides auto-detection)",
            envvar="ST_PROJECT_ID",
        ),
    ] = None,
    human: Annotated[
        bool,
        typer.Option("--human", help="Pretty-print JSON"),
    ] = False,
    compact: Annotated[
        bool,
        typer.Option(
            "--compact/--no-compact",
            "-c",
            help="TOON-style compact output (default: compact)",
        ),
    ] = True,
    progress_only: Annotated[
        bool,
        typer.Option("--progress-only", help="Progress summary only"),
    ] = False,
) -> None:
    """SummitFlow Tasks CLI."""
    if project:
        set_project_override(project)
    _apply_output_context(ctx, human=human, compact=compact, progress_only=progress_only)


if __name__ == "__main__":
    app()
