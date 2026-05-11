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

Core loop: pulse --gate | ready | claim <id> | context <id> | done <id>.
Pause/resume: pause <id> [-r reason] | resume <id> [-r reason].
VCS: vcs doctor | vcs reconcile | commit -m MSG [--task T] | jj diff | jj show.
Tools: check | graph | service | runtime | db | browser | web | sessions | agent | cleanup | logs.
Use `<command> --help` for command-specific syntax."""


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
        typer.echo(f"ERROR:st command '{self.command}' unavailable: {self.exc}", err=True)
        raise typer.Exit(1)


def _load_command_module(command: str, *, required: bool = False) -> ModuleType | _FailedCommandModule:
    try:
        return import_module(f"{__package__}.commands.{command}")
    except Exception as exc:
        if required:
            raise
        return _FailedCommandModule(command, exc)


abandon = _load_command_module("abandon")
agent = _load_command_module("agent")
agents = _load_command_module("agents")
autonomous = _load_command_module("autonomous")
autosnapshot = _load_command_module("autosnapshot")
backup = _load_command_module("backup")
browser = _load_command_module("browser")
check = _load_command_module("check", required=True)
checkpoints = _load_command_module("checkpoints")
claim = _load_command_module("claim")
claude = _load_command_module("claude")
cleanup = _load_command_module("cleanup")
complete = _load_command_module("complete")
db = _load_command_module("db")
deps = _load_command_module("deps")
design = _load_command_module("design")
docker = _load_command_module("docker")
done = _load_command_module("done")
exec_monitor = _load_command_module("exec_monitor")
feedback = _load_command_module("feedback")
git = _load_command_module("git")
graph = _load_command_module("graph")
health = _load_command_module("health")
jj = _load_command_module("jj")
logs = _load_command_module("logs")
memory = _load_command_module("memory")
persona = _load_command_module("persona")
portfolio = _load_command_module("portfolio")
projects = _load_command_module("projects")
prompt = _load_command_module("prompt")
pulse = _load_command_module("pulse")
refactor = _load_command_module("refactor")
runtime = _load_command_module("runtime")
search = _load_command_module("search")
service = _load_command_module("service")
session_events = _load_command_module("session_events")
sessions = _load_command_module("sessions")
setup = _load_command_module("setup")
snapshots = _load_command_module("snapshots")
subtask = _load_command_module("subtask")
tasks = _load_command_module("tasks")
tests = _load_command_module("tests")
tools = _load_command_module("tools")
vcs = _load_command_module("vcs")
vm = _load_command_module("vm")
web = _load_command_module("web")

app = typer.Typer(
    name="st",
    help=CLI_REFERENCE,
    no_args_is_help=True,
    rich_markup_mode=None,
)

# Register task commands at root level
for cmd in tasks.app.registered_commands:
    if cmd.callback is not None:
        app.command(name=cmd.name, hidden=cmd.hidden)(cmd.callback)

# Also register task as a subcommand group for `st task verify` / `st task import`
app.add_typer(tasks.app, name="task", hidden=True)

# Register subcommand groups (hidden from main help - reference above is complete)
app.add_typer(deps.app, name="dep")
app.add_typer(design.app, name="design")
app.add_typer(tests.app, name="test")
app.add_typer(subtask.app, name="subtask")
app.add_typer(autonomous.app, name="autonomous")
app.add_typer(claude.app, name="claude")
app.add_typer(sessions.app, name="sessions")
app.add_typer(projects.app, name="projects")
app.add_typer(git.app, name="git")
app.add_typer(graph.app, name="graph")
app.add_typer(jj.app, name="jj")
app.add_typer(vcs.app, name="vcs")
app.add_typer(backup.app, name="backup")
app.add_typer(service.app, name="service")
app.add_typer(runtime.app, name="runtime")
app.add_typer(health.app, name="health")
app.add_typer(logs.app, name="logs")
app.add_typer(memory.app, name="memory")
app.add_typer(complete.app, name="complete")
app.add_typer(agent.app, name="agent")
app.command("session-events", help="Agent Hub session events (observability)")(session_events.show_events)
app.add_typer(tools.app, name="tools")
app.add_typer(cleanup.app, name="cleanup")
app.add_typer(prompt.app, name="prompt")
app.add_typer(refactor.app, name="refactor")
app.add_typer(feedback.app, name="feedback")
app.add_typer(persona.app, name="persona")
app.add_typer(portfolio.app, name="portfolio")
app.add_typer(agents.app, name="agents")
app.add_typer(docker.app, name="docker")
app.add_typer(setup.app, name="setup")
app.add_typer(vm.app, name="vm")
app.command("pulse")(pulse.pulse)
app.command("search")(search.search)
app.command("exec-log")(exec_monitor.exec_log_command)


@app.command("commit")
@usage(
    surface="st.commit",
    cmd='st commit -m "msg" --push',
    when="user-requested work complete; off-task or residue commits",
    precautions=(
        "use --paths a b c for scoped commits when unrelated files are dirty",
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
    skip_checks: Annotated[bool, typer.Option("--skip-checks", help="Skip local check gate for local-only recovery commits.")] = False,
    bookmark: Annotated[str, typer.Option("--bookmark", help="Explicit jj bookmark to publish.")] = "",
    paths: Annotated[
        list[str] | None,
        typer.Option("--path", "--paths", help="Only commit/publish selected path(s); works for jj and plain-Git repos."),
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
        typer.echo(f"ERROR:{exc}", err=True)
        raise typer.Exit(1) from None
    if task_id and result.get("status") == "SUCCESS":
        detail_parts = [
            f"change={result.get('change_id', '')}",
            f"commit={result.get('commit_id') or result.get('sha') or ''}",
            f"bookmark={result.get('bookmark', '')}",
            f"op={result.get('operation_id', '')}",
            f"pushed={str(result.get('pushed', False)).lower()}",
        ]
        log_task_event(task_id, "st commit " + " ".join(part for part in detail_parts if not part.endswith("=")))
    if ctx.obj.is_compact:
        detail = result.get("commit_id") or result.get("sha") or result.get("reason") or ""
        print(
            f"COMMIT[1]:status={result['status']} "
            f"pushed={str(result.get('pushed', False)).lower()} detail={detail}"
        )
    else:
        from .output import output_json

        output_json(result)
    if result.get("status") == "BLOCKED":
        raise typer.Exit(2)

_FORWARD_CONTEXT_SETTINGS = {"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []}
app.command("check", context_settings=_FORWARD_CONTEXT_SETTINGS, help=check.app.info.help, add_help_option=False)(check.check)
app.command("db", context_settings=_FORWARD_CONTEXT_SETTINGS, help=db.app.info.help, add_help_option=False)(db.db)
app.command("browser", context_settings=_FORWARD_CONTEXT_SETTINGS, help=browser.app.info.help, add_help_option=False)(browser.browser)
app.command("web", context_settings=_FORWARD_CONTEXT_SETTINGS, help=web.app.info.help, add_help_option=False)(web.web)


@app.command("progress", hidden=True)
def progress_alias(
    task_id: Annotated[str | None, typer.Argument(help="Task ID")] = None,
) -> None:
    """Alias hint: use 'st sync-progress' or 'st subtask pass' instead."""
    typer.echo(
        "Command 'st progress' does not exist. Did you mean:\n"
        "  st sync-progress <task-id>              Sync objectively complete, step-backed subtasks\n"
        "  st subtask pass <subtask-id> -t <task>   Mark individual subtask complete",
        err=True,
    )
    raise typer.Exit(1)


# Register checkpoint-aware commands (override old claim from tasks.py)
# These are defined with @app.command() in their modules, so access via module.app
for cmd in claim.app.registered_commands:
    if cmd.callback is not None and cmd.name == "claim":
        app.command(name=cmd.name)(cmd.callback)
app.add_typer(checkpoints.app, name="checkpoints")
for cmd in snapshots.app.registered_commands:
    if cmd.callback is not None and cmd.name in {"snap", "snaps", "recover", "rollback", "prune"}:
        app.command(name=cmd.name, context_settings=cmd.context_settings or {})(cmd.callback)
app.add_typer(autosnapshot.app, name="autosnap", hidden=True)
for cmd in done.app.registered_commands:
    if cmd.callback is not None and cmd.name == "done":
        app.command(name="done")(cmd.callback)
for cmd in abandon.app.registered_commands:
    if cmd.callback is not None and cmd.name == "abandon":
        app.command(name="abandon")(cmd.callback)


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

    ctx.obj = OutputContext(
        human=human and not compact and not progress_only,
        compact=compact or progress_only,
        progress_only=progress_only,
    )

    set_human_output(ctx.obj.human)
    set_compact_output(ctx.obj.compact)
    set_progress_only(ctx.obj.progress_only)


if __name__ == "__main__":
    app()
