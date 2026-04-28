"""SummitFlow Tasks CLI entry point."""

import atexit
from pathlib import Path
from typing import Annotated

import typer

from app.storage.connection import close_pool
from app.storage.events import log_task_event

from .commands import (
    abandon,
    agents,
    autonomous,
    autosnapshot,
    backup,
    browser,
    check,
    checkpoints,
    claim,
    claude,
    cleanup,
    complete,
    db,
    deps,
    design,
    docker,
    done,
    exec_monitor,
    feedback,
    git,
    health,
    jj,
    logs,
    memory,
    persona,
    projects,
    prompt,
    pulse,
    refactor,
    search,
    service,
    session_events,
    sessions,
    setup,
    snapshots,
    subtask,
    tasks,
    tests,
    tools,
    vm,
    web,
)
from .commands.task_plan_contract import PLAN_SCHEMA_ENDPOINT, PLAN_VERIFY_EXAMPLE
from .config import set_project_override
from .lib.commit_workflow import CommitError, commit_repo, current_repo
from .output import set_compact_output, set_human_output, set_progress_only
from .output_context import OutputContext

# Ensure connection pool is closed on exit to avoid thread cleanup warnings
atexit.register(close_pool)

# Complete CLI reference - everything needed to use st in one place
# Format: TOON-style, optimized for Claude consumption
CLI_REFERENCE = f"""ST CLI - SummitFlow Tasks

FLAGS: --compact/-c (TOON, default) | --no-compact (raw JSON) | --human (pretty JSON) | --project/-P <id> | --progress-only
       Default output: compact TOON format. Use --no-compact for raw JSON.

WORKFLOW: pulse --gate → ready → claim <id> → context <id> → [work] → done <subtask> → done <task>
          pulse is the lane preflight: it summarizes owners, sessions, dirty trees, checkpoints, jj state, and claim/edit blockers.
          REVIEW lines mean ownerless residue: inspect context/status/logs, then commit/push/prune or leave explicit handoff. Do not auto-clean paused work.
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
  pause <id> [-r reason]                   # pause a task, release claim, keep checkpoint handoff
  resume <id> [-r reason]                  # move paused task back to pending
  cancel <id> [-r reason]                  # cancel a task (from any state)
  reopen <id> [-r reason]                  # reopen a task (move back to pending)
  sync-progress <id> [--none]              # sync passed subtasks
  autocode <id> [--dry-run] [--at TIME]    # queue for autonomous execution (immediate or scheduled)
  critique <id> [--stage task_shape]       # request/store a second-opinion critique
  verify <plan.json>                       # validate plan file against {PLAN_SCHEMA_ENDPOINT}
  exec-log <id> [-f] [-n N] [--debug]      # view execution log (subtasks, tool calls, events)

CHECKPOINT (claim -> done | abandon):
  claim <id> [--force]                     # claim task after lane preflight, create checkpoint (DB+git branch)
  claim <subtask> -t <task>                # claim subtask, create branch
  done <subtask> -t <task>                 # complete subtask, merge branch
  done <task>                              # complete task, merge to main, remove checkpoint
  abandon <subtask> -t <task>              # abandon subtask, delete branch
  abandon <task>                           # preview: show blast radius + confirm token
  abandon <task> --confirm TOKEN           # execute with token from preview
  checkpoints [-p project] [-d task]       # show active checkpoints (auto-cleans stale)
  snap [name]                              # save a Btrfs snapshot for the current project scope
  snaps                                    # list snapshots for the current project scope
  recover <id|name|-N> [--name project]    # safe default: recover snapshot into sibling project copy
  rollback <id|name|-N>                    # preview: destructive restore for current project root
  rollback <id|name|-N> --confirm TOKEN   # execute with token from preview
  prune [--dry-run]                        # remove old auto snapshots per retention policy

SUBTASK:
  subtask list <task-id>
  subtask show <task-id> <subtask-id>
  subtask create <subtask-id> -d <desc> [--task <task-id>] [--phase P]
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

VCS: commit -m "message" [--push/--no-push] [--task task-id]  # high-level st-owned VCS flow
     jj status | jj log | jj diff | jj show | jj sync | jj new -m X | jj describe -m X | jj push --task T | jj undo | jj op-log | jj op-restore OP | jj recover | jj abandon | jj restore | jj conflicts | jj revert REV
     git status | git sync | git finalize-task <task-id> | git resolve-conflict <task-id>  # git inspection/residue repair only

REFACTOR: refactor regenerate [--json]

BACKUP:
  backup list [--limit N] [--status S]
  backup create [--note 'message'] [--keep-local]
  backup archives
  backup restore [id] [--dry-run] [--confirm TOKEN] [--latest|--file PATH|--name ARCHIVE]
  backup testbed baseline [--note X] [--snapshot-name X] [--allow-dirty] [--local|--remote] [--keep-local]
  backup testbed reset [backup-id] [--rebuild|--no-rebuild] [--confirm TOKEN]
  backup status [<task-id>] [--local]
  backup schedule [--enable|--disable] [--frequency daily|weekly|monthly] [--retention N]
  backup show <id>
  backup delete <id> [--confirm TOKEN]

PERSONA: persona status | persona set-active <slug> | persona clear

AGENTS: agents list | get <slug> | update <slug> [--primary-model M] [--memory-config-file path.json]
        update supports direct memory flags: --memory-enabled/--memory-disabled,
        --audience-tags/--add-audience-tags/--remove-audience-tags, and related memory-config fields

SESSIONS: sessions list [--status S] | sessions show <id> | sessions close <id> | sessions ownership [--project P]

AUTONOMOUS: autonomous enable | disable | status

CLAUDE:
  claude task <task-id> [--feedback-text X|--feedback-file path] [--timeout-seconds N]

PROMPT: prompt list [--global] | get <slug> | create <slug> <name> -f path | update <slug> -f path [--enabled/--disabled] [--change-reason X] | delete <slug>
        prompt measure <slug> [-f path]
        prompt revisions <slug> [--limit N] | restore <slug> <revision-id> [--change-reason X]
        prompt assign <agent> <prompt> <role> [-p N] | unassign <agent> <prompt> | assignments <agent>
        prompt export [slug] [-o file] | import <file> [--dry-run]

MEMORY: memory stats | memory status [--scope S --scope-id X --consumer-profile P] | save <text> [--tier T] | list | search <query> | get <id> | delete <id>
        memory tag <id...> [--add-tags T] [--remove-tags T]

FEEDBACK: feedback report <component> <title> [--type T] [--severity S] [--session SID] [--vote-if-match] | feedback search <query>
          feedback list [--component C] [--type T] [--status S] [--sort S]
          feedback get <id> | feedback vote <id> --session <sid> | feedback resolve <id> | feedback archive <id> | feedback merge <id> <target>
          feedback summary [--project P] [--days N]

TOOLS: tools [catalog|status] [--hours N]

OPERATOR TOOLS (canonical wrapper surface):
  service status [project]                 # managed service status
  service rebuild <project> [--detach]     # build, migrate, restart, health-check
  service restart <project> [--detach]     # restart through rebuild path
  service start                            # start SummitFlow service set
  service stop [--confirm TOKEN]           # stop SummitFlow service set
  check [args...]                          # quality gates through st
  db [args...]                             # database inspection and migrations through st
  browser [browser args...]                # browser health/check/screenshot/snapshot/eval
  web [args...]                            # web search/research/fetch
  backup archives                          # list local/pending/SMB archive files
  backup restore [id] [--dry-run] [--confirm TOKEN] [--latest|--file PATH|--name ARCHIVE]
  vm list|status|snapshots|ip              # read-only Proxmox test VM operations
  vm snapshot|clone|start                  # mutating Proxmox operations
  vm stop|rollback|destroy --confirm TOKEN # destructive Proxmox operations
  setup services|browser|agent-tooling|test-dbs [--dry-run] [--confirm TOKEN]

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

CLEANUP (checkpoint maintenance):
  cleanup checkpoints                      # analyze checkpoint/legacy residue; read-only by default
  cleanup checkpoints --auto               # delete only safe legacy residue + stale checkpoints
  cleanup checkpoints --force              # destructive preview; rerun with --confirm TOKEN
  cleanup checkpoints --stale-days N       # configure stale threshold (default: 7)
  cleanup status                           # quick cleanup-debt overview (main + checkpoints + residue)
  cleanup inspect-orphans                  # list orphan task branches needing salvage/review
  cleanup salvage <task-id>                # restore a missing-task orphan branch into a branch checkpoint
  pulse [--project P] [--gate]             # lane preflight + cross-project coordination gate
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
  st pause task-abc -r "Waiting on review" # table active work without deleting state
  st resume task-abc                       # make paused task claimable again
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
app.add_typer(jj.app, name="jj")
app.add_typer(backup.app, name="backup")
app.add_typer(service.app, name="service")
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
app.add_typer(setup.app, name="setup")
app.add_typer(vm.app, name="vm")
app.command("pulse")(pulse.pulse)
app.command("search")(search.search)
app.command("exec-log")(exec_monitor.exec_log_command)


@app.command("commit")
def commit_command(
    ctx: typer.Context,
    message: Annotated[str, typer.Option("--message", "--msg", "-m", help="Required commit/change description.")],
    push: Annotated[bool, typer.Option("--push/--no-push", help="Publish after describing the change.")] = True,
    task_id: Annotated[str, typer.Option("--task", help="Task id for bookmark and audit log.")] = "",
    repo: Annotated[str | None, typer.Option("--repo", "-R", help="Repository path. Defaults to current repo.")] = None,
    skip_checks: Annotated[bool, typer.Option("--skip-checks", help="Skip local check gate for local-only recovery commits.")] = False,
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
