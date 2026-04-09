"""Task export functionality."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_success


def export_task(
    task_id: str,
    output: str | None,
    client: STClient,
) -> None:
    """Export complete task details to JSON file."""
    try:
        export_data = client.export_task_data(task_id)
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    json_str = json.dumps(export_data, indent=2, default=str)
    if output:
        Path(output).write_text(json_str)
        output_success(f"Exported to {output}")
    else:
        print(json_str)
