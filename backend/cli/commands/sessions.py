"""Agent session commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_json

app = typer.Typer(help="Agent session management")


@app.command("list")
def list_sessions(
    status_filter: Annotated[str | None, typer.Option("-s", "--status")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 20,
) -> None:
    """List agent sessions.

    Examples:
        st sessions list
        st sessions list --status running
    """
    client = STClient()

    try:
        sessions = client.list_sessions()
    except APIError as e:
        handle_api_error(e)
        return

    # Filter by status if specified
    if status_filter:
        sessions = [s for s in sessions if s.get("status") == status_filter]

    # Limit results
    sessions = sessions[:limit]

    output_json(sessions)


@app.command("show")
def show_session(
    session_id: str,
) -> None:
    """Show details of a specific session.

    Examples:
        st sessions show abc123
    """
    client = STClient()

    try:
        session = client.get_session(session_id)
    except APIError as e:
        handle_api_error(e)
        return

    output_json(session)
