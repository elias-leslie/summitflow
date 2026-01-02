"""Agent session commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import console, handle_api_error, output_json

app = typer.Typer(help="Agent session management")


@app.command("list")
def list_sessions(
    status_filter: Annotated[str | None, typer.Option("-s", "--status")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 20,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List agent sessions.

    Examples:
        st sessions list
        st sessions list --status running
        st sessions list --json
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

    if json_output:
        output_json(sessions)
        return

    if not sessions:
        console.print("[dim]No sessions found.[/dim]")
        return

    from rich.table import Table

    table = Table(title="Agent Sessions", show_header=True, header_style="bold")
    table.add_column("Session ID", style="cyan", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Agent", no_wrap=True)
    table.add_column("Tests", justify="center")
    table.add_column("Started", no_wrap=True)

    for s in sessions:
        session_id = s.get("session_id", "")[:12]
        status = s.get("status", "")
        agent = s.get("agent_type", "")
        tests_run = s.get("tests_run", 0)
        tests_passed = s.get("tests_passed", 0)
        tests_text = f"{tests_passed}/{tests_run}" if tests_run else "-"
        started = (s.get("started_at") or "")[:16]

        status_color = {
            "running": "blue",
            "completed": "green",
            "failed": "red",
        }.get(status, "dim")

        table.add_row(
            session_id,
            f"[{status_color}]{status}[/]",
            agent,
            tests_text,
            started,
        )

    console.print(table)


@app.command("show")
def show_session(
    session_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show details of a specific session.

    Examples:
        st sessions show abc123
        st sessions show abc123 --json
    """
    client = STClient()

    try:
        session = client.get_session(session_id)
    except APIError as e:
        handle_api_error(e)
        return

    if json_output:
        output_json(session)
        return

    from rich.panel import Panel

    session_id_short = session.get("session_id", "")
    status = session.get("status", "")
    agent = session.get("agent_type", "")

    status_color = {"running": "blue", "completed": "green", "failed": "red"}.get(status, "dim")

    content_lines = [
        f"[bold]Status:[/bold] [{status_color}]{status}[/]",
        f"[bold]Agent:[/bold] {agent}",
    ]

    started = session.get("started_at")
    ended = session.get("ended_at")
    if started:
        content_lines.append(f"[bold]Started:[/bold] {started[:19]}")
    if ended:
        content_lines.append(f"[bold]Ended:[/bold] {ended[:19]}")

    # Test results
    tests_run = session.get("tests_run", 0)
    tests_passed = session.get("tests_passed", 0)
    tests_failed = session.get("tests_failed", 0)
    if tests_run:
        content_lines.append(
            f"\n[bold]Tests:[/bold] {tests_passed}/{tests_run} passed, {tests_failed} failed"
        )

    # Capabilities
    caps_attempted = session.get("capabilities_attempted", [])
    caps_passed = session.get("capabilities_passed", [])
    caps_failed = session.get("capabilities_failed", [])
    if caps_attempted:
        content_lines.append("\n[bold]Capabilities:[/bold]")
        content_lines.append(f"  Attempted: {len(caps_attempted)}")
        content_lines.append(f"  [green]Passed: {len(caps_passed)}[/]")
        content_lines.append(f"  [red]Failed: {len(caps_failed)}[/]")

    # Notes
    notes = session.get("notes")
    if notes:
        content_lines.append("\n[bold]Notes:[/bold]")
        content_lines.append(f"  {notes[:200]}")

    panel = Panel(
        "\n".join(content_lines),
        title=f"Session {session_id_short}",
        border_style=status_color,
    )
    console.print(panel)
