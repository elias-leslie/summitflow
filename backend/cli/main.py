"""SummitFlow Tasks CLI entry point."""

import atexit
from typing import Annotated

import typer

from app.storage.connection import close_pool

from .commands import (
    abandon,
    autonomous,
    backup,
    checkpoints,
    claim,
    cleanup,
    close,
    complete,
    deps,
    done,
    exec_monitor,
    git,
    health,
    logs,
    memory,
    projects,
    prompt,
    refactor,
    session_events,
    sessions,
    step,
    subtask,
    tasks,
    tests,
    tools,
)
from .config import set_project_override
from .output import set_compact_output, set_human_output, set_progress_only
from .output_context import OutputContext

# Ensure connection pool is closed on exit to avoid thread cleanup warnings
atexit.register(close_pool)

# Complete CLI reference - everything needed to use st in one place
# Format: TOON-style, optimized for Claude consumption
CLI_REFERENCE = """ST CLI - SummitFlow Tasks

FLAGS: --compact/-c (TOON, default) | --no-compact (raw JSON) | --human (pretty JSON) | --project/-P <id> | --progress-only
       Default output: compact TOON format. Use --no-compact for raw JSON.

WORKFLOW: ready → claim <id> → context <id> → [work] → done <subtask> → done <task>
          Alternative: abandon <id> to rollback

TASKS:
  create <title> [-t feature|bug|task|chore] [-p 0-4] [-d desc] [--blocked-by id]
  list [--status S] [--type T] [--priority P]
  ready                                    # unblocked tasks
  context <id> [--subtask X.Y]             # full task/subtask context (TOON format)
  export <id> [-o file.json]               # full JSON export (everything)
  log <id> <message>
  cancel <id> [-r reason]                  # cancel a task (from any state)
  autocode <id> [--dry-run] [--at TIME]    # queue for autonomous execution (immediate or scheduled)
  verify <plan.json>                       # validate plan file against schema
  exec-log <id> [-f] [-n N] [--debug]      # view execution log (subtasks, tool calls, events)

CHECKPOINT (claim -> done | close | abandon):
  claim <id> [--force]                     # claim task, create checkpoint (DB+git)
  claim <subtask> -t <task>                # claim subtask, create branch
  done <subtask> -t <task>                 # complete subtask, merge branch
  done <task>                              # complete task, merge to main, remove checkpoint
  close <task> [--force]                   # complete task (code-only), delete branches, no merge
  abandon <subtask> -t <task>              # abandon subtask, delete branch
  abandon <task> [--force]                 # abandon task, restore DB, delete branches
  checkpoints [-p project] [-d task]       # show active checkpoints (auto-cleans stale)

SUBTASK:
  subtask list <task-id>
  subtask show <task-id> <subtask-id>
  subtask create <task-id> <sub-id> <desc> [--phase P] [--steps "a,b,c"]
  subtask pass <task-id> <subtask-id>
  subtask delete <task-id> <subtask-id>

STEP:
  step list <task-id> <subtask-id>
  step pass <task-id> <subtask-id> <step#>
  step create <task-id> <subtask-id> --steps "a,b,c"
  step add <task-id> <subtask-id> --steps "a,b,c"
  step delete <task-id> <subtask-id> <step#>

DEP:
  dep list <task-id>
  dep add <task-id> <depends-on-id>
  dep rm <task-id> <depends-on-id>

PROJECTS: projects list | projects current

TEST: test list [--type T] | import --framework pytest|vitest

GIT: git status | git sync

REFACTOR: refactor regenerate [--json]

BACKUP:
  backup list [--limit N] [--status S]
  backup create [--note 'message'] [--keep-local]
  backup restore <id> [--dry-run] [--yes]
  backup status [<task-id>]
  backup schedule [--enable|--disable] [--frequency daily|weekly|monthly] [--retention N]
  backup show <id>
  backup delete <id> [--yes]

SESSIONS: sessions list [--status S] | sessions show <id>

AUTONOMOUS: autonomous enable | disable | status

PROMPT: prompt list [--global] | get <slug> | create <slug> <name> -f path | update <slug> -f path | delete <slug>
        prompt assign <agent> <prompt> <role> [-p N] | unassign <agent> <prompt> | assignments <agent>
        prompt seed [--dir path] [--dry-run] | sync [--dir path] [--dry-run]

MEMORY: memory stats | save <text> [--tier T] | list | search <query> | get <id> | delete <id>

TOOLS: tools status [--hours N]

LOGS (unified service logs):
  logs                                   # show recent logs (default: tail)
  logs tail [-s service] [-l level] [-n lines] [--since time] [-f]
  logs services                          # list available services
  logs levels                            # show log level counts

HEALTH (quality gate):
  health                                   # show quality gate summary (default)
  health status                            # same as above
  health results [--type T] [--status S] [--unfixed] [--limit N]
  health sync <type> <status> [--errors N] [--warnings N] [--triggered-by commit|manual|ci|agent]

CLEANUP (worktree maintenance):
  cleanup worktrees                        # list orphaned/stale worktrees with recommendations
  cleanup worktrees --auto                 # auto-cleanup safe cases (merged, no commits ahead)
  cleanup worktrees --force                # cleanup all worktrees (with confirmation)
  cleanup worktrees --stale-days N         # configure stale threshold (default: 7)
  cleanup status                           # quick worktree status overview

EXAMPLES:
  st ready                                 # find work (compact by default)
  st claim task-abc                        # claim task, create checkpoint
  st context task-abc                      # view full context
  st context task-abc --subtask 1.1        # view subtask context
  st step pass 1.1 1 -t task-abc           # mark step 1 done
  st done 1.1 -t task-abc                  # complete subtask, merge branch
  st done task-abc                         # complete task, remove checkpoint
  st abandon task-abc --force              # rollback everything
  st checkpoints                           # show active checkpoints
  st checkpoints                           # show active checkpoints

SESSION EVENTS (Agent Hub observability):
  session-events <session-id>              # view events by session ID
  session-events --task <task-id>          # view events by task ID (auto-resolves sessions)
  session-events --task <task-id> -f       # follow in real-time
  session-events --task <task-id> -t tool_use  # filter to tool calls only
"""

app = typer.Typer(
    name="st",
    help=CLI_REFERENCE,
    no_args_is_help=True,
)

# Register task commands at root level
for cmd in tasks.app.registered_commands:
    if cmd.callback is not None:
        app.command(name=cmd.name, hidden=cmd.hidden)(cmd.callback)

# Also register task as a subcommand group for `st task verify` / `st task import`
app.add_typer(tasks.app, name="task", hidden=True)

# Register subcommand groups (hidden from main help - reference above is complete)
app.add_typer(deps.app, name="dep")
app.add_typer(tests.app, name="test")
app.add_typer(subtask.app, name="subtask")
app.add_typer(step.app, name="step")
app.add_typer(autonomous.app, name="autonomous")
app.add_typer(sessions.app, name="sessions")
app.add_typer(projects.app, name="projects")
app.add_typer(git.app, name="git")
app.add_typer(backup.app, name="backup")
app.add_typer(health.app, name="health")
app.add_typer(logs.app, name="logs")
app.add_typer(memory.app, name="memory")
app.add_typer(complete.app, name="complete")
app.add_typer(session_events.app, name="session-events")
app.add_typer(tools.app, name="tools")
app.add_typer(cleanup.app, name="cleanup")
app.add_typer(prompt.app, name="prompt")
app.add_typer(refactor.app, name="refactor")
app.command("exec-log")(exec_monitor.exec_log_command)
app.command("exec-monitor", hidden=True)(exec_monitor.exec_monitor_command)  # alias

# Register checkpoint-aware commands (override old claim from tasks.py)
# These are defined with @app.command() in their modules, so access via module.app
for cmd in claim.app.registered_commands:
    if cmd.callback is not None and cmd.name == "claim":
        app.command(name="claim")(cmd.callback)
app.add_typer(checkpoints.app, name="checkpoints")
for cmd in done.app.registered_commands:
    if cmd.callback is not None and cmd.name == "done":
        app.command(name="done")(cmd.callback)
for cmd in abandon.app.registered_commands:
    if cmd.callback is not None and cmd.name == "abandon":
        app.command(name="abandon")(cmd.callback)
for cmd in close.app.registered_commands:
    if cmd.callback is not None and cmd.name == "close":
        app.command(name="close")(cmd.callback)


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
