"""Component commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_json

app = typer.Typer(help="Component management commands")


@app.command("list")
def list_components() -> None:
    """List all components.

    Examples:
        st component list
    """
    client = STClient()

    try:
        components = client.list_components()
    except APIError as e:
        handle_api_error(e)
        return

    output_json(components)


@app.command()
def show(
    component_id: str,
) -> None:
    """Show component details.

    Examples:
        st component show cli
    """
    client = STClient()

    try:
        comp = client.get_component(component_id)
    except APIError as e:
        handle_api_error(e)
        return

    output_json(comp)


@app.command()
def create(
    component_id: str,
    name: Annotated[str | None, typer.Option("--name", "-n")] = None,
    description: Annotated[str | None, typer.Option("--description", "-d")] = None,
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
        handle_api_error(e)
        return

    output_json(comp)
