"""Session events command - View Agent Hub session events for observability."""

from __future__ import annotations

from typing import Annotated, Any, cast

import httpx
import typer

from ..config import get_agent_hub_url
from ..output import output_error, output_json

app = typer.Typer(help="Agent Hub session events (observability)")


def _load_credentials() -> tuple[str, str, str]:
    """Load credentials from ~/.env.local."""
    from pathlib import Path

    env_file = Path.home() / ".env.local"
    if not env_file.exists():
        output_error("~/.env.local not found")
        raise typer.Exit(1)

    creds: dict[str, str] = {}
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, val = line.split("=", 1)
            creds[key.strip()] = val.strip()

    client_id = creds.get("SUMMITFLOW_CLIENT_ID") or creds.get("CONSULT_CLIENT_ID")
    client_secret = creds.get("SUMMITFLOW_CLIENT_SECRET") or creds.get("CONSULT_CLIENT_SECRET")
    request_source = creds.get("SUMMITFLOW_REQUEST_SOURCE", "st-session-events")

    if not client_id or not client_secret:
        output_error(
            "Missing CONSULT_CLIENT_ID/SECRET or SUMMITFLOW_CLIENT_ID/SECRET in ~/.env.local"
        )
        raise typer.Exit(1)

    return client_id, client_secret, request_source


def _get_session_events(
    session_id: str,
    event_type: str | None = None,
    turn: int | None = None,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    """Fetch session events from Agent Hub."""
    client_id, client_secret, request_source = _load_credentials()

    headers = {
        "X-Client-Id": client_id,
        "X-Client-Secret": client_secret,
        "X-Request-Source": request_source,
    }

    params: dict[str, Any] = {
        "page": page,
        "page_size": page_size,
    }
    if event_type:
        params["event_type"] = event_type
    if turn is not None:
        params["turn"] = turn

    agent_hub_url = get_agent_hub_url()
    url = f"{agent_hub_url}/api/sessions/{session_id}/events"

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers, params=params)

            if response.status_code >= 400:
                try:
                    detail = response.json().get("detail", response.text)
                except Exception:
                    detail = response.text
                output_error(f"API error ({response.status_code}): {detail}")
                raise typer.Exit(1) from None

            return cast(dict[str, Any], response.json())
    except httpx.ConnectError:
        output_error(f"Cannot connect to Agent Hub at {agent_hub_url}")
        raise typer.Exit(1) from None
    except typer.Exit:
        raise
    except Exception as e:
        output_error(f"Request failed: {e}")
        raise typer.Exit(1) from None


def _format_event(event: dict[str, Any], verbose: bool = False) -> str:
    """Format a single event for display."""
    event_type = event.get("event_type", "unknown")
    turn = event.get("turn", 0)
    seq = event.get("sequence", 0)
    content = event.get("content") or ""
    tool_name = event.get("tool_name")
    tokens = event.get("tokens")
    model = event.get("model_used")

    # Color codes for different event types
    type_colors = {
        "user_message": "\033[36m",  # Cyan
        "assistant_message": "\033[32m",  # Green
        "system_message": "\033[33m",  # Yellow
        "thinking": "\033[35m",  # Magenta
        "tool_use": "\033[34m",  # Blue
        "tool_result": "\033[34m",  # Blue
        "memory_inject": "\033[90m",  # Gray
        "memory_cite": "\033[90m",  # Gray
        "error": "\033[31m",  # Red
    }
    reset = "\033[0m"
    color = type_colors.get(event_type, "")

    # Build header
    header = f"{color}[{turn}.{seq}] {event_type}{reset}"
    if tool_name:
        header += f" ({tool_name})"
    if tokens:
        header += f" [{tokens} tokens]"
    if model and verbose:
        header += f" [{model}]"

    # Build content preview
    if event_type in ("tool_use", "tool_result"):
        tool_input = event.get("tool_input")
        tool_output = event.get("tool_output")
        if event_type == "tool_use" and tool_input:
            # Show abbreviated input
            import json

            input_str = json.dumps(tool_input)
            if len(input_str) > 100 and not verbose:
                input_str = input_str[:100] + "..."
            content = input_str
        elif event_type == "tool_result" and tool_output:
            import json

            output_str = json.dumps(tool_output)
            if len(output_str) > 100 and not verbose:
                output_str = output_str[:100] + "..."
            content = output_str

    # Truncate content for display
    if content and len(content) > 200 and not verbose:
        content = content[:200] + "..."

    if content:
        # Indent content
        indented = "  " + content.replace("\n", "\n  ")
        return f"{header}\n{indented}"
    return header


@app.callback(invoke_without_command=True)
def show_events(
    ctx: typer.Context,
    session_id: Annotated[str | None, typer.Argument(help="Session ID to view")] = None,
    event_type: Annotated[
        str | None,
        typer.Option(
            "-t",
            "--type",
            help="Filter by event type (user_message, assistant_message, thinking, tool_use, tool_result, etc.)",
        ),
    ] = None,
    turn: Annotated[int | None, typer.Option("--turn", help="Filter by turn number")] = None,
    page: Annotated[int, typer.Option("--page", help="Page number")] = 1,
    page_size: Annotated[int, typer.Option("--page-size", "-n", help="Events per page")] = 50,
    raw: Annotated[bool, typer.Option("--raw", "-r", help="Output raw JSON")] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show full content without truncation")
    ] = False,
) -> None:
    """View session events for full observability.

    Shows the complete execution timeline including:
    - User/assistant/system messages
    - Thinking blocks
    - Tool calls and results
    - Memory injections and citations

    Examples:
        st session-events abc123
        st session-events abc123 --type tool_use
        st session-events abc123 --turn 2
        st session-events abc123 --raw
        st session-events abc123 -v
    """
    if ctx.invoked_subcommand is not None:
        return

    if not session_id:
        typer.echo(ctx.get_help())
        return

    result = _get_session_events(session_id, event_type, turn, page, page_size)

    if raw:
        output_json(result)
        return

    events = result.get("events", [])
    total = result.get("total", 0)
    max_turn = result.get("max_turn", 0)

    if not events:
        typer.echo("No events found for this session.")
        return

    # Header
    typer.echo(f"\n Session: {session_id}")
    typer.echo(f" Events: {total} | Max turn: {max_turn}")
    if event_type:
        typer.echo(f" Filter: type={event_type}")
    if turn is not None:
        typer.echo(f" Filter: turn={turn}")
    typer.echo("-" * 60)

    # Display events
    for event in events:
        typer.echo(_format_event(event, verbose))
        typer.echo()

    # Footer
    if len(events) < total:
        typer.echo(f"Showing {len(events)} of {total} events (page {page})")
