"""Autonomous execution commands for the CLI."""

from __future__ import annotations

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_json

app = typer.Typer(help="Autonomous execution management")


@app.command()
def enable() -> None:
    """Enable autonomous execution for the project.

    Examples:
        st autonomous enable
    """
    client = STClient()

    try:
        result = client.update_autonomous_settings(enabled=True)
    except APIError as e:
        handle_api_error(e)
        return

    output_json(result)


@app.command()
def disable() -> None:
    """Disable autonomous execution for the project.

    Examples:
        st autonomous disable
    """
    client = STClient()

    try:
        result = client.update_autonomous_settings(enabled=False)
    except APIError as e:
        handle_api_error(e)
        return

    output_json(result)
