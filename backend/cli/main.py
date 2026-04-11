"""SummitFlow Tasks CLI entry point."""

import atexit
from typing import Annotated

import typer

from app.storage.connection import close_pool

from .commands import (
    abandon,
    agents,
    autonomous,
    autosnapshot,
    backup,
    checkpoints,
    claim,
    claude,
    cleanup,
    complete,
    deps,
    design,
    docker,
    done,
    exec_monitor,
    feedback,
    git,
    health,
    logs,
    memory,
    persona,
    projects,
    prompt,
    pulse,
    refactor,
    search,
    session_events,
    sessions,
    snapshots,
    subtask,
    tasks,
    tests,
    tools,
)
from .commands.task_plan_contract import PLAN_SCHEMA_ENDPOINT, PLAN_VERIFY_EXAMPLE
from .config import set_project_override
from .output import set_compact_output, set_human_output, set_progress_only
from .output_context import OutputContext

# Ensure connection pool is closed on exit to avoid thread cleanup warnings
atexit.register(close_pool)

# Complete CLI reference - everything needed to use st in one place
# Format: TOON-style, optimized for Claude consumption
CLI_REFERENCE = f"""ST CLI - SummitFlow Tasks

FLAGS: --compact/-c (TOON, default) | --no-compact (raw JSON) | --human (pretty JSON) | --project/-P <id> | --progress-only
       Default output: compact TOON format. Use --no-compact for raw JSON.

WORKFLOW: ready → claim <id> → context <id> → [work] → done <subtask> → done <task>
          Alternative: abandon <id> --discard to rollback

TASKS (create/capture REQUIRE -P <project>):
  create --plan <plan.json> [--task existing-id]   # REQUIRES -P; execution-ready import
  create --from-file <tasks.json> [--dry-run]      # REQUIRES -P; batch task import
  capture <task|bug|idea> <title> [--description X] [--priority N] [--labels a,b]  # REQUIRES -P
  list [--status S] [--type T] [--priority P]
  ready                                    # unblocked tasks (current project)
  ready-all [--limit N]                    # cross-project summary: ready + blocked tasks
  context <id> [--subtask X.Y]             # full task/subtask context (TOON format)
  export <id> [-o file.json]               # full JSON export (everything)
  log <id> <message>
  cancel <id> [-r reason]                  # cancel a task (from any state)
  reopen <id> [-r reason]                  # reopen a task (move back to pending)
  sync-progress <id> [--none]              # sync passed subtasks
  autocode <id> [--dry-run] [--at TIME]    # queue for autonomous execution (immediate or scheduled)
  critique <id> [--stage task_shape]       # request/store a second-opinion critique
  verify <plan.json>                       # validate plan file against {PLAN_SCHEMA_ENDPOINT}
  exec-log <id> [-f] [-n N] [--debug]      # view execution log (subtasks, tool calls, events)

CHECKPOINT (claim -> done | abandon):
  claim <id> [--force]                     # claim task, create checkpoint (DB+git, auto-adopt dirty files)
  adopt <id>                               # copy current dirty paths into an existing claimed worktree
  claim <subtask> -t <task>                # claim subtask, create branch
  done <subtask> -t <task>                 # complete subtask, merge branch
  done <task>                              # complete task, merge to main, remove checkpoint
  abandon <subtask> -t <task>              # abandon subtask, delete branch
  abandon <task>                           # preview: show blast radius + confirm token
  abandon <task> --confirm TOKEN           # execute with token from preview
  checkpoints [-p project] [-d task]       # show active checkpoints (auto-cleans stale)
  snap [name]                              # save a Btrfs snapshot for the current lane or project scope
  snaps                                    # list snapshots for the current lane or project scope
  recover <id|name|-N> [--name lane]       # safe default: recover snapshot into sibling lane/project copy
  rollback <id|name|-N>                    # preview: destructive restore for current task lane
  rollback <id|name|-N> --confirm TOKEN   # execute with token from preview
  prune [--dry-run]                        # remove old auto snapshots per retention policy

SUBTASK:
  subtask list <task-id>
  subtask show <task-id> <subtask-id>
  subtask create <task-id> <sub-id> <desc> [--phase P] [--steps "a,b,c"]
  subtask pass <subtask-id> -t <task-id> [--citation M:abc12345+] [--none]
  subtask delete <task-id> <subtask-id>

DEP:
  dep list <task-id>
  dep add <task-id> <depends-on-id>
  dep rm <task-id> <depends-on-id>

PROJECTS: projects [list|current|get|root|create|update|delete]

DESIGN:
  design ui analyze <page-url> [--page-path /foo]                                  # REQUIRES -P
  design asset generate <name> <prompt> [--type sprite_sheet] [--workflow production] [--variants N]
                      [--size 1024x1024] [--background transparent|solid|scene]
                      [--style "..."] [--negative "..."] [--tags a,b]              # REQUIRES -P
  design asset export <asset-id> [--type sprite-frames]                            # REQUIRES -P

TEST: test list [--type T] | import --framework pytest|vitest

GIT: git status | git sync | git finalize-task <task-id>

REFACTOR: refactor regenerate [--json]

BACKUP:
  backup list [--limit N] [--status S]
  backup create [--note 'message'] [--keep-local]
  backup restore <id> [--dry-run] [--yes]
  backup testbed baseline [--note X] [--snapshot-name X] [--allow-dirty] [--local|--remote] [--keep-local]
  backup testbed reset [backup-id] [--rebuild|--no-rebuild] [--confirm TOKEN]
  backup status [<task-id>]
  backup schedule [--enable|--disable] [--frequency daily|weekly|monthly] [--retention N]
  backup show <id>
  backup delete <id> [--yes]

PERSONA: persona status | persona set-active <slug> | persona clear

AGENTS: agents list | get <slug> | update <slug> [--primary-model M] [--memory-config-file path.json]
        update supports direct memory flags: --memory-enabled/--memory-disabled,
        --audience-tags/--add-audience-tags/--remove-audience-tags, and related memory-config fields

SESSIONS: sessions list [--status S] | sessions show <id> | sessions close <id> | sessions ownership [--project P]

AUTONOMOUS: autonomous enable | disable | status

CLAUDE:
  claude task <task-id> [--feedback-text X|--feedback-file path] [--timeout-seconds N]

PROMPT: prompt list [--global] | get <slug> | create <slug> <name> -f path | update <slug> -f path [--enabled/--disabled] [--change-reason X] | delete <slug>
        prompt revisions <slug> [--limit N] | restore <slug> <revision-id> [--change-reason X]
        prompt assign <agent> <prompt> <role> [-p N] | unassign <agent> <prompt> | assignments <agent>
        prompt export [slug] [-o file] | import <file> [--dry-run]

MEMORY: memory stats | memory status [--scope S --scope-id X --consumer-profile P] | save <text> [--tier T] | list | search <query> | get <id> | delete <id>
        memory tag <id...> [--add-tags T] [--remove-tags T]

FEEDBACK: feedback report <component> <title> [--type T] [--severity S] [--session SID] [--vote-if-match] | feedback search <query>
          feedback list [--component C] [--type T] [--status S] [--sort S]
          feedback get <id> | feedback vote <id> --session <sid> | feedback resolve <id> | feedback archive <id> | feedback merge <id> <target>
          feedback summary [--project P] [--days N]

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
  cleanup worktrees                        # analyze worktrees; read-only by default
  cleanup worktrees --auto                 # delete only SAFE/ALREADY_MERGED worktrees
  cleanup worktrees --force                # destructive preview; rerun with --confirm TOKEN
  cleanup worktrees --stale-days N         # configure stale threshold (default: 7)
  cleanup status                           # quick cleanup-debt overview (main + worktrees + residue)
  cleanup inspect-orphans                  # list orphan task branches needing salvage/review
  cleanup salvage <task-id>                # restore a missing-task orphan branch into a lane
  pulse [--project P]                      # cross-project coordination summary (default); drill down with --project
  cleanup path <path> [<path>...]          # safe literal path cleanup
  cleanup path <dir> --recursive           # safe literal directory cleanup
  cleanup path <path> --dry-run            # preview cleanup without deleting

DOCKER:
  docker status                              # container health grid (TOON format)
  docker up [--profile X] [--dev] [-d]       # start compose stack
  docker down [--volumes]                    # stop compose stack
  docker restart [service]                   # restart one or all containers
  docker logs <service> [-f] [-n N]          # tail container logs
  docker build [--push] [--tag X]            # build all Docker images
  docker pull                                # pull latest images
  docker shell <service>                     # interactive shell in container
  docker backup [--note X]                   # pg_dumpall from Docker postgres
  docker restore <archive>                   # restore from SQL dump
  docker env-create <name> [--profile X]     # create ephemeral test environment
  docker env-list                            # list test environments
  docker env-destroy <name|--all>            # tear down test environment
  docker env-exec <name> <service> <cmd>     # run command in test environment service
  docker metrics                             # CPU/memory per container

EXAMPLES:
  st -P summitflow create --plan plan.json  # create execution-ready task (explicit project)
  {PLAN_VERIFY_EXAMPLE}                      # validate plan.json against the live schema
  st -P agent-hub capture bug "Fix auth"   # capture bug kernel (explicit project)
  st -P summitflow capture idea "Add dark mode"  # capture idea kernel (explicit project)
  st -P monkey-fight design ui analyze http://localhost:4001
  st -P monkey-fight design asset generate "Kiki attack sheet" "Capuchin fighter combo sheet" --type sprite_sheet --workflow production --sheet-columns 4 --sheet-rows 2 --frame-width 128 --frame-height 128 --animations idle,attack
  st ready                                 # find work (compact by default)
  st claim task-abc                        # claim task, create checkpoint
  st context task-abc                      # view full context
  st context task-abc --subtask 1.1        # view subtask context
  st done 1.1 -t task-abc                  # complete subtask, merge branch
  st done task-abc                         # complete task, remove checkpoint
  st abandon task-abc                      # preview blast radius
  st abandon task-abc --confirm TOKEN     # execute with confirm token
  st checkpoints                           # show active checkpoints
  st claude task task-abc                  # run task through Claude Code worker wrapper

SEARCH (Precision Code Search):
  search <query>                           # symbol-first search with fallback
  search <query> --budget 2000             # custom token budget
  search <query> --json                    # full JSON payload

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
app.add_typer(backup.app, name="backup")
app.add_typer(health.app, name="health")
app.add_typer(logs.app, name="logs")
app.add_typer(memory.app, name="memory")
app.add_typer(complete.app, name="complete")
app.command("session-events", help="Agent Hub session events (observability)")(session_events.show_events)
app.add_typer(tools.app, name="tools")
app.add_typer(cleanup.app, name="cleanup")
app.add_typer(prompt.app, name="prompt")
app.add_typer(refactor.app, name="refactor")
app.add_typer(feedback.app, name="feedback")
app.add_typer(persona.app, name="persona")
app.add_typer(agents.app, name="agents")
app.add_typer(docker.app, name="docker")
app.command("pulse")(pulse.pulse)
app.command("search")(search.search)
app.command("exec-log")(exec_monitor.exec_log_command)


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
    if cmd.callback is not None and cmd.name in {"claim", "adopt"}:
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
