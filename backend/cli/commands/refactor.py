"""Refactor task management commands."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_json

app = typer.Typer(help="Refactor task management")


@app.command()
def regenerate(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output raw JSON for programmatic use")
    ] = False,
    sync: Annotated[
        bool,
        typer.Option(
            "--sync",
            help="Run synchronously and wait for final counts. Default queues background sync.",
        ),
    ] = False,
) -> None:
    """Synchronize refactor tasks with the current Explorer scan.

    Queues background work by default so large projects are not held behind an HTTP timeout.

    Examples:
        st refactor regenerate
        st refactor regenerate --json
        st refactor regenerate --sync
    """
    client = STClient(timeout=None) if sync else STClient()
    url = client._url("/explorer/regenerate-refactor-tasks")

    try:
        params = {"sync": "true"} if sync else None
        result = client.post(url, params=params)
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    if json_output:
        output_json(result)
    else:
        if result.get("status") == "started":
            typer.echo(f"REFACTOR_SYNC: status=started project={result.get('project_id', client.project_id)}")
            return
        closed = result.get("closed_count", 0)
        created = result.get("created_count", 0)
        scanned = result.get("scanned_count", 0)
        typer.echo(f"REFACTOR_SYNC: closed={closed} created={created} scanned={scanned}")
