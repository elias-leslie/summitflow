"""Canonical browser automation command surface."""

from __future__ import annotations

import typer

from .operator_forward import run_forwarded

app = typer.Typer(
    help="Remote browser automation. Uses the managed browser runner.",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)


@app.callback(invoke_without_command=True)
def browser(ctx: typer.Context) -> None:
    """Run browser health, checks, screenshots, snapshots, or DOM commands.

    Examples:
      st browser health
      st browser check http://localhost:3001 /tmp/summitflow.png
    """
    if ctx.invoked_subcommand is not None:
        return
    run_forwarded("sf-browser", list(ctx.args))
