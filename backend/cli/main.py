"""SummitFlow Tasks CLI entry point."""

import typer

app = typer.Typer(name="st", help="SummitFlow Tasks CLI")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """SummitFlow Tasks CLI - task management for development workflows."""
    if ctx.invoked_subcommand is None:
        print(ctx.get_help())


if __name__ == "__main__":
    app()
