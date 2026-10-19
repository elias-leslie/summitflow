"""SummitFlow Tasks CLI entry point."""

import atexit
import sys
from functools import cache
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Annotated, Any, cast

import typer
import typer.main
from typer.core import TyperGroup

from .config import set_project_override
from .extensions import ExtensionCommand, register_extensions
from .lib.usage import usage
from .output import set_compact_output, set_human_output, set_progress_only
from .output_context import OutputContext


def _close_pool_if_opened() -> None:
    """Close the connection pool on exit, only when a command opened storage."""
    connection = sys.modules.get("app.storage.connection")
    if connection is not None:
        connection.close_pool()


atexit.register(_close_pool_if_opened)

CLI_REFERENCE = """ST: managed-project tools for agents.

Discover: search "<query>" | tools manifest --surface <surface>.
Task work: ready | claim <id> | context <id> | check | commit -m MSG | done <id>.
Task state: pause <id> | reopen <id> | cancel <id> | update <id>.
Inspect: pulse | vcs doctor | service status | browser --help.
Use `st <command> --help` for command-specific syntax. Global options precede the command; -P/--project also works after it."""

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

# Root commands whose modules import on first use, so `st --help` and every other
# command skip importing all command modules. name -> (module, kind, attribute,
# help listed in root --help, hidden). Kinds: "named" registers module.app's
# command of that name, "group" adds module.app as a group, "call" registers the
# module attribute, "forward" passes argv through to the module attribute.
# The help here is only the one-line root --help listing; `st <command> --help`
# shows the module's own help.
LAZY_COMMANDS: dict[str, tuple[str, str, str, str, bool]] = {
    "checkout-job": ("checkout_job", "forward", "checkout_job", "Run an internal agent checkout job.", True),
    "create": ("tasks", "named", "", "Create a pending task.", False),
    "list": ("tasks", "named", "", "List tasks with optional filters.", False),
    "ready": ("tasks", "named", "", "List claimable tasks, or use --blocked to inspect blocked pending tasks.", False),
    "ready-all": ("tasks", "named", "", "Cross-project summary: ready and blocked tasks across all projects.", False),
    "context": ("tasks", "named", "", "Get task or subtask context in a single call.", False),
    "export": ("tasks", "named", "", "Export complete task details to JSON file.", False),
    "cancel": ("tasks", "named", "", "Cancel a task (mark as cancelled from any state).", False),
    "pause": ("tasks", "named", "", "Pause a task and release its active claim.", False),
    "reopen": ("tasks", "named", "", "Reopen a task (move it back to pending).", False),
    "delete": ("tasks", "named", "", "Delete a task.", False),
    "update": ("tasks", "named", "", "Update in-flight task fields.", False),
    "log": ("tasks", "named", "", "Append a task log entry.", False),
    "sync-progress": ("tasks", "named", "", "Sync subtask pass state from already-completed steps.", False),
    "verify": ("tasks", "named", "", "Verify a plan.json file against the live schema and task-domain rules.", False),
    "critique": ("tasks", "named", "", "Request and store a second-opinion critique for a task.", False),
    SESSION_EVENTS_COMMAND: ("session_events", "call", "show_events", "Agent Hub session events (observability)", False),
    "pulse": ("pulse", "call", "pulse", "Show the canonical live coordination pulse and optional preflight gate.", False),
    "lease": ("lease", "call", "lease_command", "File-level lease for parallel-agent coordination.", False),
    "exec-log": ("exec_monitor", "call", "exec_log_command", "View execution progress for a task.", False),
    "check": ("check", "forward", "check", "Quality checks through st.", False),
    "db": ("db", "forward", "db", "Database inspection and migration commands through the managed st surface.", False),
    "claim": ("claim", "named", "", "Claim a task or subtask to start work.", False),
    "snap": ("snapshots", "named", "", "Capture a Btrfs snapshot for the current project scope.", False),
    "snaps": ("snapshots", "named", "", "List snapshots for the current project scope.", False),
    "recover": ("snapshots", "named", "", "Inspect a read-only side copy or preview/apply selected owned files.", False),
    "rollback": ("snapshots", "named", "", "Destructively restore the current project root to a recorded snapshot.", False),
    "prune": ("snapshots", "named", "", "Remove old auto snapshots per retention policy.", False),
    "done": ("done", "named", "", "Complete a task or subtask.", False),
    "abandon": ("abandon", "named", "", "Abandon a task or subtask and roll back tracked code changes.", False),
    "task": ("tasks", "group", "", "Task management commands", True),
    "dep": ("deps", "group", "", "Dependency management commands", False),
    "test": ("tests", "group", "", "Test management commands", False),
    "subtask": ("subtask", "group", "", "Subtask management commands", False),
    "claude": ("claude", "group", "", "Claude Code worker dispatch", False),
    "sessions": ("sessions", "group", "", "Agent session management.", False),
    "projects": ("projects", "group", "", "Project management commands", False),
    "git": ("git", "group", "", "Low-level Git inspection and residue repair.", False),
    "vcs": ("vcs", "group", "", "Canonical VCS hygiene and exact-source publication.", False),
    "backup": ("backup", "group", "", "Backup management commands", False),
    "service": ("service", "group", "", "Project service lifecycle through st.", False),
    "runtime": ("runtime", "group", "", "Runtime observability.", False),
    "health": ("health", "group", "", "Quality gate health and status", False),
    "logs": ("logs", "group", "", "View and tail service logs", False),
    "monitor": ("monitor", "group", "", "System and project troubleshooting: bounded JSON with coverage, freshness, and cursors.", False),
    "agent": ("agent", "group", "", "Run Agent Hub agents with tools", False),
    "tools": ("tools", "group", "", "Operator tool catalog and Agent Hub usage metrics", False),
    "cleanup": ("cleanup", "group", "", "Clean up git/checkpoint residue plus managed workspace leftovers.", False),
    "docker": ("docker", "group", "", "Docker stack control for the SummitFlow ecosystem (through Nightshift).", False),
    "setup": ("setup", "group", "", "Host, service, tooling, and test database setup through st.", False),
    "vm": ("vm", "group", "", "Proxmox VM lifecycle through st: status, IPs, snapshots, start/stop/shutdown/reboot, resize, rollback, clone.", False),
    "checkpoints": ("checkpoints", "group", "", "Checkpoint management - show active checkpoints, cleanup stale artifacts", False),
    "autosnap": ("autosnapshot", "group", "", "Internal autosnapshot commands (systemd timer / hooks)", True),
}
_LISTING = "st.listing"


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


def _register_lazy(target: typer.Typer, name: str) -> None:
    """Register the real command for one LAZY_COMMANDS entry on ``target``."""
    module_name, kind, attribute, help_text, hidden = LAZY_COMMANDS[name]
    module = _load_command_module(module_name, required=module_name == "check")
    if kind == "group":
        target.add_typer(module.app, name=name, hidden=hidden)
    elif kind == "call":
        target.command(name, help=help_text if name == SESSION_EVENTS_COMMAND else None)(getattr(module, attribute))
    elif kind == "forward":
        target.command(
            name, context_settings=FORWARD_CONTEXT_SETTINGS, help=module.app.info.help, add_help_option=False, hidden=hidden,
        )(getattr(module, attribute))
    else:
        for cmd in module.app.registered_commands:
            if cmd.callback is not None and (cmd.name or typer.main.get_command_name(getattr(cmd.callback, "__name__", ""))) == name:
                target.command(
                    name=name, hidden=cmd.hidden, help=cmd.help, short_help=cmd.short_help, epilog=cmd.epilog,
                    context_settings=cmd.context_settings or {},
                )(cmd.callback)
                return
        if not isinstance(module, _FailedCommandModule):
            raise LookupError(f"{module_name} defines no command {name!r}")
        target.command(name, help=module.app.info.help)(module.unavailable)


@cache
def _lazy_command(name: str) -> Any:
    target = typer.Typer(rich_markup_mode=None)
    _register_lazy(target, name)
    group = typer.main.get_group(target)
    return group.commands[name]


def _lazy_placeholder() -> None:  # pragma: no cover - _RootGroup resolves the real command
    raise RuntimeError("lazy st command placeholder invoked")


def _register_lazy_placeholders() -> None:
    """List lazy commands (and reserve their names from extensions) without importing them."""
    for name, (_module, _kind, _attribute, help_text, hidden) in LAZY_COMMANDS.items():
        app.command(
            name, help=help_text, hidden=hidden, add_help_option=False, context_settings=FORWARD_CONTEXT_SETTINGS,
        )(_lazy_placeholder)


def _materialize_lazy_commands() -> None:
    """Replace the placeholders with the real commands; st_sdk.usage calls this before walking."""
    if getattr(app, "_st_materialized", False):
        return
    cast(Any, app)._st_materialized = True
    app.registered_commands[:] = [cmd for cmd in app.registered_commands if cmd.callback is not _lazy_placeholder]
    for name in LAZY_COMMANDS:
        _register_lazy(app, name)


def _event_detail_parts(result: dict[str, object]) -> list[str]:
    return [
        f"commit={result.get('sha') or ''}",
        f"pushed={str(result.get('pushed', False)).lower()}",
        *([f"publication_complete={str(result['publication_complete']).lower()}"] if "publication_complete" in result else []),
    ]


def _log_commit_event(task_id: str, result: dict[str, object]) -> None:
    from app.storage.events import log_task_event

    detail = " ".join(part for part in _event_detail_parts(result) if not part.endswith("="))
    log_task_event(task_id, f"{COMMIT_EVENT_PREFIX} {detail}")


def _print_budget_line() -> None:
    """One informational line after a commit; never fails the commit."""
    try:
        import subprocess

        from cli.lib.quality_budget import (
            budget_line,
            environment_disabled,
            load_baseline,
            measure,
            regressions,
        )

        if environment_disabled():
            return
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
        if top.returncode == 0:
            root = Path(top.stdout.strip())
            current = measure(root)
            print(budget_line(current, regressions(current, load_baseline(root))))
    except Exception:
        return


def _emit_commit_output(ctx: typer.Context, result: dict[str, object]) -> None:
    if ctx.obj.is_compact:
        detail = result.get("sha") or result.get("reason") or ""
        print(
            COMMIT_COMPACT_TEMPLATE.format(
                status=result["status"],
                pushed=str(result.get("pushed", False)).lower(),
                detail=detail,
            )
        )
        if result.get("status") == SUCCESS_STATUS:
            _print_budget_line()
        if result.get("reason") == "quality_gates_failed":
            check_detail = result.get("detail")
            if isinstance(check_detail, str):
                for line in check_detail.splitlines():
                    if ":FAIL:" in line:
                        print(line)
        if "ci" in result:
            ci = cast(dict[str, Any], result["ci"])
            if isinstance(ci, dict):
                print(f"CI:state={ci.get('state')} sha={ci.get('sha')} pr={result.get('pr_url', '')} merge={result.get('merge_sha', '')}")
                if ci.get("detail"):
                    print(f"CI:detail={ci['detail']}")
                for check in ci.get("checks", []):
                    if check.get("state") != "success":
                        print(f"CI:check={check.get('name')} state={check.get('state')} url={check.get('url') or ''}")
            print("DEPLOYMENT:state=not_run")
            if result.get("local_reconciliation"):
                print(f"LOCAL:{result['local_reconciliation']}")
        return

    from .output import output_json

    output_json(result)


def _apply_output_context(ctx: typer.Context, *, human: bool, compact: bool, progress_only: bool) -> None:
    ctx.obj = OutputContext(
        human=human and not compact and not progress_only,
        compact=compact or progress_only,
        progress_only=progress_only,
    )
    set_human_output(ctx.obj.human)
    set_compact_output(ctx.obj.compact)
    set_progress_only(ctx.obj.progress_only)

_PROJECT_FLAGS = ("-P", "--project")


def _declares_project(command: Any) -> bool:
    return any(flag in _PROJECT_FLAGS for param in command.params for flag in getattr(param, "opts", ()))


def _passes_unknown_options(command: Any) -> bool:
    # Extensions own their argv verbatim. Their passthrough lives in
    # context_settings, which Click applies to the Context, not the Command.
    return isinstance(command, ExtensionCommand) or bool(command.ignore_unknown_options or command.allow_extra_args)


def _project_tokens(args: list[str], start: int) -> tuple[list[str], list[str]]:
    """Split ``-P X``/``--project X``/``--project=X``/``-PX`` after ``start`` (before ``--``)."""
    kept, moved = args[:start], []
    index = start
    while index < len(args):
        token = args[index]
        if token == "--":
            kept.extend(args[index:])
            break
        if token in _PROJECT_FLAGS and index + 1 < len(args):
            moved.extend(args[index:index + 2])
            index += 2
            continue
        if token.startswith("--project=") or (token.startswith("-P") and len(token) > 2):
            moved.append(token)
        else:
            kept.append(token)
        index += 1
    return kept, moved


def hoist_global_project(group: Any, ctx: typer.Context, args: list[str]) -> list[str]:
    """Let ``st <command> ... -P X`` mean ``st -P X <command> ...``.

    Commands that declare their own -P/--project, or pass unknown options
    through (extensions), keep the flag where it was written.
    """
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in _PROJECT_FLAGS else 1
    if index >= len(args):
        return args
    command: Any = group
    position = index
    # Typer vendors Click, so recognise groups by interface, not class.
    while hasattr(command, "get_command") and position < len(args):
        sub = command.get_command(ctx, args[position])
        if sub is None:
            break
        if _declares_project(sub) or _passes_unknown_options(sub):
            return args
        command, position = sub, position + 1
        while position < len(args) and args[position].startswith("-") and args[position] != "--":
            position += 1
    kept, moved = _project_tokens(args, index + 1)
    return [*moved, *kept] if moved else args


class _RootGroup(TyperGroup):
    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:  # Typer vendors Click's Context
        return super().parse_args(ctx, hoist_global_project(self, ctx, list(args)))

    def get_command(self, ctx: Any, cmd_name: str) -> Any:
        if cmd_name in LAZY_COMMANDS and not ctx.meta.get(_LISTING):
            return _lazy_command(cmd_name)
        return super().get_command(ctx, cmd_name)

    def format_commands(self, ctx: Any, formatter: Any) -> None:
        # Root help lists the placeholders' help instead of importing every command module.
        ctx.meta[_LISTING] = True
        try:
            super().format_commands(ctx, formatter)
        finally:
            ctx.meta.pop(_LISTING, None)


app = typer.Typer(
    name="st",
    cls=_RootGroup,
    help=CLI_REFERENCE,
    no_args_is_help=True,
    rich_markup_mode=None,
)

_register_lazy_placeholders()
cast(Any, app).st_materialize = _materialize_lazy_commands


@app.command("commit", context_settings={"allow_extra_args": True})
@usage(
    surface="st.commit",
    cmd='st commit -m "msg"',
    when="authorized work reaches a verified checkpoint",
    precautions=(
        "review diff for destructive changes, scope",
        "--paths preserves unrelated work; include the checkpoint's generated changes",
        "publication: st vcs publish --source ID --sha FULL_OID --now",
        "commit before destructive ops (abandon, rollback)",
    ),
    tier="mandate",
)
def commit_command(
    ctx: typer.Context,
    message: Annotated[str, typer.Option("--message", "--msg", "-m", help="Required commit description.")],
    push: Annotated[bool, typer.Option("--push/--no-push", help="Unsupported; publish accepted source with st vcs publish.")] = False,
    task_id: Annotated[str, typer.Option("--task", help="Task id for checkpoint and audit log.")] = "",
    repo: Annotated[str | None, typer.Option("--repo", "-R", help="Repository path. Defaults to current repo.")] = None,
    skip_checks: Annotated[
        bool,
        typer.Option("--skip-checks", help="Skip local check gate for local-only recovery commits."),
    ] = False,
    paths: Annotated[
        list[str] | None,
        typer.Option(
            "--path",
            "--paths",
            help=(
                "Only commit selected path(s); takes several values "
                "(--paths a b) or repeats (--paths a --paths b)."
            ),
        ),
    ] = None,
    with_ack: Annotated[
        str | None,
        typer.Option("--with-ack", help="Request id the repo's holder acked yes (st sessions send ... --delivery handshake)."),
    ] = None,
) -> None:
    """Run checks and create a local checkpoint; publish accepted source separately."""
    from .lib.commit_workflow import (
        COMMIT_PUBLICATION_GUIDANCE,
        CommitError,
        commit_repo,
        current_repo,
    )

    try:
        if ctx.args:
            # Click options take one value each; the words after --paths a arrive as extra arguments.
            if not paths:
                raise CommitError(f"unexpected argument(s): {' '.join(ctx.args)}; select paths with --paths a b")
            paths = [*paths, *ctx.args]
        if push:
            raise CommitError(COMMIT_PUBLICATION_GUIDANCE)
        repo_path = current_repo() if repo is None else Path(repo).expanduser().resolve()
        result = commit_repo(
            repo_path,
            message=message,
            task_id=task_id,
            push=push,
            skip_checks=skip_checks,
            paths=tuple(paths or ()),
            **({"with_ack": with_ack} if with_ack else {}),
        )
    except CommitError as exc:
        typer.echo(f"{COMMIT_ERROR_PREFIX}{exc}", err=True)
        raise typer.Exit(1) from None

    if task_id and result.get("status") == SUCCESS_STATUS:
        _log_commit_event(task_id, result)
    _emit_commit_output(ctx, result)
    if result.get("status") in {BLOCKED_STATUS, "PENDING"}:
        raise typer.Exit(2)


@app.command(PROGRESS_COMMAND, hidden=True)
def progress_alias(
    task_id: Annotated[str | None, typer.Argument(help="Task ID")] = None,
) -> None:
    """Alias hint: use 'st sync-progress' or 'st done <subtask-id> -t <task-id>' instead."""
    typer.echo(PROGRESS_ALIAS_MESSAGE, err=True)
    raise typer.Exit(1)


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
        typer.Option("--human", help="Indent JSON; requires --no-compact and no --progress-only"),
    ] = False,
    compact: Annotated[
        bool,
        typer.Option(
            "--compact/--no-compact",
            "-c",
            help="Compact structured output; --no-compact selects JSON where supported",
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


# All core/hidden names are registered before extension collision checks.
register_extensions(app)


if __name__ == "__main__":
    app()
