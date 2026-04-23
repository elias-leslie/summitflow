"""Project service lifecycle commands."""

from __future__ import annotations

from typing import Annotated

import typer

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
