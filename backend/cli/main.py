"""SummitFlow Tasks CLI entry point."""

import typer

from .commands import (
    autonomous,
    capabilities,
    components,
    deps,
    sessions,
    step,
    subtask,
    tasks,
    tests,
    worktree,
)

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


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """SummitFlow Tasks CLI - task management for development workflows."""
    if ctx.invoked_subcommand is None:
        print(ctx.get_help())


if __name__ == "__main__":
    app()
