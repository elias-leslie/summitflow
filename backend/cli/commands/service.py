"""Project service lifecycle commands."""

from __future__ import annotations

from typing import Annotated

import typer

from ..lib.confirm_token import confirm_gate
from .operator_forward import run_forwarded

app = typer.Typer(help="Project service lifecycle and rebuild commands")


@app.command()
def status(
    project: Annotated[
        str | None,
        typer.Argument(help="Project id. Omit to show all projects."),
    ] = None,
) -> None:
    """Show managed service status through the canonical service path."""
    args = ["--status"]
    if project:
        args.append(project)
    run_forwarded("rebuild.sh", args)


@app.command()
def rebuild(
    project: Annotated[str, typer.Argument(help="Project id to rebuild")],
    detach: Annotated[bool, typer.Option("--detach", help="Queue rebuild in background")] = False,
    include_all_workers: Annotated[
        bool,
        typer.Option("--include-all-workers", help="Restart protected optional workers too"),
    ] = False,
) -> None:
    """Build, migrate, restart, and health-check a project."""
    args: list[str] = []
    if detach:
        args.append("--detach")
    if include_all_workers:
        args.append("--include-all-workers")
    args.append(project)
    run_forwarded("rebuild.sh", args)


@app.command()
def restart(
    project: Annotated[str, typer.Argument(help="Project id to restart/rebuild")],
    detach: Annotated[bool, typer.Option("--detach", help="Queue restart in background")] = False,
    include_all_workers: Annotated[
        bool,
        typer.Option("--include-all-workers", help="Restart protected optional workers too"),
    ] = False,
) -> None:
    """Restart a managed project through the rebuild path."""
    args: list[str] = []
    if detach:
        args.append("--detach")
    if include_all_workers:
        args.append("--include-all-workers")
    args.append(project)
    run_forwarded("rebuild.sh", args)


@app.command()
def start() -> None:
    """Start the SummitFlow platform service set."""
    run_forwarded("start.sh", [])


@app.command()
def stop(
    confirm: Annotated[str | None, typer.Option("--confirm", help="Confirm token from preview run")] = None,
) -> None:
    """Stop SummitFlow services. Two-pass confirmation required."""
    confirm_gate(
        "service-stop-summitflow",
        confirm,
        [
            "STOP SERVICES: summitflow frontend/backend",
            "This interrupts active local SummitFlow sessions.",
        ],
        "st service stop",
    )
    run_forwarded("shutdown.sh", [])
