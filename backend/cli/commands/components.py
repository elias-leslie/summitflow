"""Component commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import console, output_error, output_json, output_success

app = typer.Typer(help="Component management commands")


def _handle_api_error(e: APIError) -> None:
    """Handle API error and exit."""
    output_error(e.detail)
    raise typer.Exit(1)


@app.command("list")
def list_components(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List all components.

    Examples:
        st component list
        st component list --json
    """
    client = STClient()

    try:
        components = client.list_components()
    except APIError as e:
        _handle_api_error(e)
        return

    if json_output:
        output_json(components)
    else:
        from rich.table import Table

        table = Table(title="Components", show_header=True)
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="bold")
        table.add_column("Description")
        table.add_column("Capabilities", justify="right")

        for comp in components:
            table.add_row(
                comp.get("component_id", "-"),
                comp.get("name", "-"),
                (comp.get("description") or "-")[:50],
                str(comp.get("capability_count", 0)),
            )

        console.print(table)


@app.command()
def show(
    component_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show component details.

    Examples:
        st component show cli
        st component show cli --json
    """
    client = STClient()

    try:
        comp = client.get_component(component_id)
    except APIError as e:
        _handle_api_error(e)
        return

    if json_output:
        output_json(comp)
    else:
        from rich.panel import Panel

        content = [
            f"[bold]{comp.get('name', component_id)}[/bold]",
            "",
            f"ID: {comp.get('component_id', '-')}",
            f"DB ID: {comp.get('id', '-')}",
        ]

        if comp.get("description"):
            content.append(f"\n{comp['description']}")

        panel = Panel("\n".join(content), title=f"[cyan]{component_id}[/]")
        console.print(panel)


@app.command()
def create(
    component_id: str,
    name: Annotated[str | None, typer.Option("--name", "-n")] = None,
    description: Annotated[str | None, typer.Option("--description", "-d")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Create a new component.

    Args:
        component_id: Component ID slug (e.g., "cli-tools")
        name: Display name (defaults to component_id if not provided)
        description: Optional description

    Examples:
        st component create cli-tools
        st component create cli-tools --name "CLI Tools" -d "Command line interface"
    """
    client = STClient()

    # Use component_id as name if not provided
    display_name = name or component_id.replace("-", " ").title()

    try:
        comp = client.create_component(
            component_id=component_id,
            name=display_name,
            description=description,
        )
    except APIError as e:
        _handle_api_error(e)
        return

    if json_output:
        output_json(comp)
    else:
        output_success(f"Created component '{component_id}' (ID: {comp.get('id')})")
