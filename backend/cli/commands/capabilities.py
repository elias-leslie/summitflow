"""Capability commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import output_capabilities, output_error, output_json, output_success

app = typer.Typer(help="Capability management commands")


def _handle_api_error(e: APIError) -> None:
    """Handle API error and exit."""
    output_error(e.detail)
    raise typer.Exit(1)


@app.command("list")
def list_caps(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List all capabilities.

    Examples:
        st capability list
        st capability list --json
    """
    client = STClient()

    try:
        caps = client.list_capabilities()
    except APIError as e:
        _handle_api_error(e)
        return

    output_capabilities(caps, json_output)


@app.command()
def show(
    capability_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show capability details.

    Examples:
        st capability show login
        st capability show login --json
    """
    client = STClient()

    try:
        # List all and filter (no direct get endpoint)
        caps = client.list_capabilities()
        cap = next((c for c in caps if c["capability_id"] == capability_id), None)
    except APIError as e:
        _handle_api_error(e)
        return

    if not cap:
        output_error(f"Capability '{capability_id}' not found")
        raise typer.Exit(1)

    if json_output:
        output_json(cap)
    else:
        from rich.console import Console
        from rich.panel import Panel

        console = Console()
        status = cap.get("status", "pending")
        color = {"pending": "yellow", "tests_passing": "green"}.get(status, "white")

        content = [
            f"[bold]{cap.get('name', capability_id)}[/bold]",
            "",
            f"ID: {capability_id}",
            f"Status: [{color}]{status}[/]",
            f"Priority: P{cap.get('priority', 2)}",
        ]

        if cap.get("description"):
            content.append(f"\n{cap['description']}")

        if cap.get("verification_url"):
            content.append(f"\nVerification URL: {cap['verification_url']}")

        panel = Panel("\n".join(content), title=f"[cyan]{capability_id}[/]", border_style=color)
        console.print(panel)


@app.command()
def create(
    capability_id: str,
    component: Annotated[str, typer.Option("--component", "-c")],
    name: Annotated[str | None, typer.Option("--name", "-n")] = None,
    description: Annotated[str | None, typer.Option("--description", "-d")] = None,
    priority: Annotated[int, typer.Option("--priority", "-p")] = 2,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Create a new capability.

    Args:
        capability_id: Capability ID slug (e.g., "user-login")
        component: Component ID (integer or slug)
        name: Display name (defaults to capability_id if not provided)
        description: Optional description
        priority: Priority level (0-4, default 2)

    Examples:
        st capability create user-login --component cli
        st capability create user-login -c cli --name "User Login" -p 1
    """
    client = STClient()

    # Use capability_id as name if not provided
    display_name = name or capability_id.replace("-", " ").title()

    # Resolve component ID if it's a slug
    try:
        comp = client.get_component(component)
        component_id = comp["id"]
    except APIError:
        # Maybe it's already an integer ID
        try:
            component_id = int(component)
        except ValueError:
            output_error(f"Component '{component}' not found")
            raise typer.Exit(1) from None

    try:
        cap = client.create_capability(
            component_id=component_id,
            capability_id=capability_id,
            name=display_name,
            description=description,
            priority=priority,
        )
    except APIError as e:
        _handle_api_error(e)
        return

    if json_output:
        output_json(cap)
    else:
        output_success(f"Created capability '{capability_id}' (ID: {cap.get('id')})")


@app.command()
def verify(
    capability_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Verify a capability's tests.

    Examples:
        st capability verify login
        st capability verify login --json
    """
    client = STClient()

    try:
        result = client.verify_capability(capability_id)
    except APIError as e:
        _handle_api_error(e)
        return

    if json_output:
        output_json(result)
    else:
        status = result.get("capability_status", "unknown")
        if status == "tests_passing":
            output_success(f"Capability '{capability_id}' verified - all tests passing")
        else:
            output_error(f"Capability '{capability_id}' verification failed: {status}")
