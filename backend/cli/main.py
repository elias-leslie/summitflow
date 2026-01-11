"""SummitFlow Tasks CLI entry point."""

from typing import Annotated

import typer

from .commands import (
    autonomous,
    capabilities,
    components,
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

FLAGS: --compact(-c) --human --project(-P)<id> --progress-only

WORKFLOW: ready → update <id> --status running → subtask list <id> → [work] → step pass → subtask pass → close <id> --reason "..."

TASKS:
  create <title> [-t feature|bug|task|chore] [-p 0-4] [-d desc]
  list [--status S] [--type T] [--priority P]
  ready                                    # unblocked tasks
  show <id>... [--full] [--summary]        # --summary=one-liner
  inspect <id>...                          # id|status|done/total
  update <id> [--status S] [-d desc] [-p 0-4] [--objective text] [--branch name] [--pr-url url] [--parent id]
  close <id> --reason <text>
  cancel <id> --reason <text>
  delete <id>
  bug <title> [-p 0-4] [-d desc]           # shorthand: create -t bug
  claim <id> [--lock 30] [--release]       # lock task for N minutes
  exec <id> [--agent claude|gemini]
  log <id> <message>
  autocode <id> [--status exec-id] [--abort exec-id] [--model M] [--dry-run]

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

CAPABILITY: capability list | show <id> | create <name> --component <id> | update <id> [--name N] [-d desc] [-p 0-4] [-s status] | verify <id>

COMPONENT: component list | show <id> | create <name> [-d desc]

CRITERION:
  criterion list --capability <cap-id>                             # list criteria for capability
  criterion create <text> --capability <cap-id> [--category C] [--measurement M] [--threshold T]
  criterion update <id> [--criterion text] [--category C] [--measurement M] [--threshold T]
  criterion verify <task-id> <criterion-id> --by test|manual       # verify criterion for task

TEST: test list [--type T] | link <id> --criterion <id> | import --framework pytest|vitest

WORKTREE: worktree list | worktree prune

GIT: git status | git sync

SESSIONS: sessions list [--status S] | sessions show <id>

AUTONOMOUS: autonomous enable | disable | status

EXAMPLES:
  st --compact ready                       # find work
  st update task-abc --status running      # claim
  st --compact subtask list task-abc       # view subtasks
  st step pass task-abc 1.1 1              # mark step 1 done
  st subtask pass task-abc 1.1             # mark subtask done
  st close task-abc --reason "Done"        # complete task
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
app.add_typer(capabilities.app, name="capability")
app.add_typer(capabilities.app, name="cap", hidden=True)  # Alias
app.add_typer(tests.app, name="test")
app.add_typer(subtask.app, name="subtask")
app.add_typer(step.app, name="step")
app.add_typer(autonomous.app, name="autonomous")
app.add_typer(sessions.app, name="sessions")
app.add_typer(worktree.app, name="worktree")
app.add_typer(components.app, name="component")
app.add_typer(criterion.app, name="criterion")
app.add_typer(projects.app, name="projects")
app.add_typer(git.app, name="git")


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
        typer.Option("--compact", "-c", help="TOON-style compact output"),
    ] = False,
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
