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
) -> None:
    """Delete existing refactor tasks and regenerate from current scan.

    Runs synchronously — blocks until complete, then reports results.

    Examples:
        st refactor regenerate
        st refactor regenerate --json
    """
    client = STClient(timeout=300.0)
    url = client._url("/explorer/regenerate-refactor-tasks")

    try:
        result = client.post(url, params={"sync": "true"})
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    if json_output:
        output_json(result)
    else:
        deleted = result.get("deleted_count", 0)
        created = result.get("created_count", 0)
        scanned = result.get("scanned_count", 0)
        typer.echo(f"REGENERATE: deleted={deleted} created={created} scanned={scanned}")
