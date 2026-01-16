"""SummitFlow Tasks CLI entry point."""

from typing import Annotated

import typer

from .commands import (
    autonomous,
    backup,
    criterion,
    deps,
    git,
    projects,
    sessions,
    step,
    subtask,
    tasks,
    tests,
    worktree,
)
from .config import set_project_override
from .output import set_compact_output, set_human_output, set_progress_only

# Complete CLI reference - everything needed to use st in one place
# Format: TOON-style, optimized for Claude consumption
CLI_REFERENCE = """ST CLI - SummitFlow Tasks

FLAGS: --compact/-c (TOON, default) | --no-compact (raw JSON) | --human (pretty JSON) | --project/-P <id> | --progress-only
       Default output: compact TOON format. Use --no-compact for raw JSON.

WORKFLOW: ready → update <id> --status running → subtask list <id> → [work] → step pass → subtask pass → close <id> --reason "..."

TASKS:
  create <title> [-t feature|bug|task|chore] [-p 0-4] [-d desc] [--blocked-by id]
  list [--status S] [--type T] [--priority P]
  ready                                    # unblocked tasks
  show <id>... [--full] [--summary]        # --summary=one-liner
  inspect <id>...                          # id|status|done/total
  context <id>                             # full task context (TOON format)
  export <id> [-o file.json]               # full JSON export (everything)
  update <id> [--status S] [-d desc] [-p 0-4] [--objective text] [--blocked-by id] [--unblock id]
  approve <id>                             # approve plan for execution
  close <id> --reason <text>
  cancel <id> --reason <text>
  delete <id>
  bug <title> [-p 0-4] [-d desc]           # shorthand: create -t bug
  claim <id> [--lock 30] [--release]       # lock task for N minutes
  exec <id> [--agent claude|gemini]
  log <id> <message>
  autocode <id> [--status exec-id] [--abort exec-id] [--model M] [--dry-run]

QA:
  qa pass <task-id>                        # mark QA passed (required before close)
  qa fail <task-id>                        # mark QA failed
  qa skip <task-id> [--force]              # skip QA (SIMPLE tasks only, or --force)

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

CRITERION:
  criterion list --task <task-id>                                  # list criteria for task
  criterion create <text> --task <task-id> [--category C] [--verify-by test|agent|human] [--verify-command cmd] [--expected-output text]
  criterion update <id> [--criterion text] [--category C] [--verify-command cmd] [--verify-by M] [--expected-output text]
  criterion preflight --task <task-id>                             # TDD preflight: verify commands fail
  criterion amend <task-id> <criterion-id> --new-command <cmd> --reason <text>  # request verify_command change
  criterion override <task-id> <criterion-id> --action pass|reset --reason <text>  # human override

AMENDMENT:
  amendment list [--task <task-id>] [--status pending|approved|rejected]
  amendment approve <amendment-id> [--reason text]
  amendment reject <amendment-id> --reason <text>

TEST: test list [--type T] | link <id> --criterion <id> | import --framework pytest|vitest

WORKTREE: worktree list | worktree prune

GIT: git status | git sync

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

EXAMPLES:
  st ready                                 # find work (compact by default)
  st update task-abc --status running      # claim
  st subtask list task-abc                 # view subtasks
  st step pass task-abc 1.1 1              # mark step 1 done
  st subtask pass task-abc 1.1             # mark subtask done
  st close task-abc --reason "Done"        # complete task
  st --human show task-abc                 # verbose JSON output
"""

app = typer.Typer(
    name="st",
    help=CLI_REFERENCE,
    no_args_is_help=True,
)

# Register task commands at root level
for cmd in tasks.app.registered_commands:
    app.command(name=cmd.name)(cmd.callback)

# Also register task as a subcommand group for `st task verify` / `st task import`
app.add_typer(tasks.app, name="task", hidden=True)

# Register subcommand groups (hidden from main help - reference above is complete)
app.add_typer(deps.app, name="dep")
app.add_typer(tests.app, name="test")
app.add_typer(subtask.app, name="subtask")
app.add_typer(step.app, name="step")
app.add_typer(autonomous.app, name="autonomous")
app.add_typer(sessions.app, name="sessions")
app.add_typer(worktree.app, name="worktree")
app.add_typer(criterion.app, name="criterion")
from .commands import amendment  # noqa: E402 - imported here to register after criterion

app.add_typer(amendment.app, name="amendment")
app.add_typer(projects.app, name="projects")
app.add_typer(git.app, name="git")
app.add_typer(backup.app, name="backup")
app.add_typer(tasks.qa_app, name="qa")


@app.callback()
def main(
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
    set_human_output(human and not compact and not progress_only)
    set_compact_output(compact or progress_only)
    set_progress_only(progress_only)


if __name__ == "__main__":
    app()
