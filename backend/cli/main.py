"""SummitFlow Tasks CLI entry point."""

import typer

from .commands import capabilities, deps, subtask, tasks, tests

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


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """SummitFlow Tasks CLI - task management for development workflows."""
    if ctx.invoked_subcommand is None:
        print(ctx.get_help())


if __name__ == "__main__":
    app()
