"""Canonical quality-check command surface."""

from __future__ import annotations

import typer

from .operator_forward import run_forwarded

app = typer.Typer(
    help="Quality checks through the managed st surface.",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)


@app.callback(invoke_without_command=True)
def check(ctx: typer.Context) -> None:
    """Run quality gates or named check subcommands.

    Examples:
      st check --quick --changed-only
      st check pytest -- backend/tests/cli/test_tools_cli.py
    """
    if ctx.invoked_subcommand is not None:
        return
    run_forwarded("dt", list(ctx.args))
