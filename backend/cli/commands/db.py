"""Canonical database command surface."""

from __future__ import annotations

import typer

from .operator_forward import run_forwarded

app = typer.Typer(
    help="Database inspection and migration commands. Forwards to the managed db runner.",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)


@app.callback(invoke_without_command=True)
def db(ctx: typer.Context) -> None:
    """Run database inspection or migration commands.

    Examples:
      st db tables
      st db migrate status
    """
    if ctx.invoked_subcommand is not None:
        return
    run_forwarded("db", list(ctx.args))
