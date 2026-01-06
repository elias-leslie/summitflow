"""SummitFlow Tasks CLI entry point."""

from typing import Annotated

import typer

from .commands import (
    autonomous,
    capabilities,
    components,
    criterion,
    deps,
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

app = typer.Typer(name="st", help="SummitFlow Tasks CLI")

# Register task commands at root level
for cmd in tasks.app.registered_commands:
    app.command(name=cmd.name)(cmd.callback)

# Register subcommand groups
app.add_typer(deps.app, name="dep", help="Dependency management")
app.add_typer(capabilities.app, name="capability", help="Capability management")
app.add_typer(capabilities.app, name="cap", hidden=True)  # Alias
app.add_typer(tests.app, name="test", help="Test management")
app.add_typer(subtask.app, name="subtask", help="Subtask management")
app.add_typer(step.app, name="step", help="Step management")
app.add_typer(autonomous.app, name="autonomous", help="Autonomous execution")
app.add_typer(sessions.app, name="sessions", help="Agent sessions")
app.add_typer(worktree.app, name="worktree", help="Git worktrees")
app.add_typer(components.app, name="component", help="Component management")
app.add_typer(criterion.app, name="criterion", help="Criterion management")
app.add_typer(projects.app, name="projects", help="Project management")


@app.command(name="commands")
def list_all_commands() -> None:
    """List all commands and subcommands."""
    # Root commands
    print("ROOT COMMANDS:")
    for cmd in tasks.app.registered_commands:
        name = cmd.name or cmd.callback.__name__
        doc = (cmd.callback.__doc__ or "").split("\n")[0]
        print(f"  st {name:20} {doc}")

    # Subcommand groups with their commands
    subgroups = [
        ("dep", deps.app, "Dependency management"),
        ("subtask", subtask.app, "Subtask management"),
        ("step", step.app, "Step management"),
        ("capability", capabilities.app, "Capability management"),
        ("component", components.app, "Component management"),
        ("criterion", criterion.app, "Criterion management"),
        ("test", tests.app, "Test management"),
        ("worktree", worktree.app, "Git worktrees"),
        ("sessions", sessions.app, "Agent sessions"),
        ("autonomous", autonomous.app, "Autonomous execution"),
        ("projects", projects.app, "Project management"),
    ]

    for group_name, subapp, description in subgroups:
        print(f"\n{group_name.upper()} ({description}):")
        for cmd in subapp.registered_commands:
            name = cmd.name or cmd.callback.__name__
            doc = (cmd.callback.__doc__ or "").split("\n")[0]
            print(f"  st {group_name} {name:14} {doc}")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    project: Annotated[
        str | None,
        typer.Option(
            "-P",
            "--project",
            help="Project ID to use (overrides auto-detection)",
            envvar="ST_PROJECT_ID",
        ),
    ] = None,
    human: Annotated[
        bool,
        typer.Option(
            "--human",
            help="Pretty-print JSON output for human readability",
        ),
    ] = False,
    compact: Annotated[
        bool,
        typer.Option(
            "--compact",
            "-c",
            help="TOON-style compact output (one line per item)",
        ),
    ] = False,
    progress_only: Annotated[
        bool,
        typer.Option(
            "--progress-only",
            help="Show only progress summary (single line)",
        ),
    ] = False,
) -> None:
    """SummitFlow Tasks CLI - task management for development workflows.

    Project is auto-detected from current directory. Override with -P/--project.
    Output is compact JSON by default. Use --human for pretty-printed output.
    Use --compact for TOON-style one-liner per item.
    """
    # Set project override if provided
    if project:
        set_project_override(project)

    # Set output modes (mutually exclusive: compact > progress_only > human)
    set_human_output(human and not compact and not progress_only)
    set_compact_output(compact or progress_only)
    set_progress_only(progress_only)

    if ctx.invoked_subcommand is None:
        print(ctx.get_help())


if __name__ == "__main__":
    app()
