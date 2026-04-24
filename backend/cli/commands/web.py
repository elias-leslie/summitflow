"""Canonical public web research command surface."""

from __future__ import annotations

import typer

from .operator_forward import run_forwarded

app = typer.Typer(
    help="Public web search, research, and fetch through the shared Agent Hub stack.",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)


@app.callback(invoke_without_command=True)
def web(ctx: typer.Context) -> None:
    """Run shared web research commands.

    Examples:
      st web search --query "SummitFlow" --limit 1
      st web fetch --url https://example.com --focus-query title
    """
    if ctx.invoked_subcommand is not None:
        return
    run_forwarded("web-research", list(ctx.args))
