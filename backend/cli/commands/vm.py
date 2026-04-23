"""Canonical VM operations command surface."""

from __future__ import annotations

import typer

from .operator_forward import run_forwarded

app = typer.Typer(
    help="Proxmox test VM lifecycle commands. Destructive operations remain guarded by the backend runner.",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)


@app.callback(invoke_without_command=True)
def vm(ctx: typer.Context) -> None:
    """Run VM list, status, snapshot, rollback, clone, power, destroy, or ip commands.

    Examples:
      st vm list
      st vm status 100
    """
    if ctx.invoked_subcommand is not None:
        return
    run_forwarded("proxmox-vm.sh", list(ctx.args))
