"""Capability commands for the CLI.

DEPRECATED: The capability system has been replaced by task-based acceptance criteria.
Use `st criterion create --task <task-id>` to create criteria linked to tasks.
These commands will be removed in a future version.
"""

from __future__ import annotations

import sys
from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import (
    handle_api_error,
    output_capabilities,
    output_error,
    output_json,
)

app = typer.Typer(help="[DEPRECATED] Capability management commands - use task criteria instead")


def _warn_deprecated() -> None:
    """Print deprecation warning."""
    print(
        "\033[33mWARNING: The capability system is deprecated. "
        "Use 'st criterion create --task <task-id>' instead.\033[0m",
        file=sys.stderr,
    )


@app.command("list")
def list_caps() -> None:
    """List all capabilities.

    Examples:
        st capability list
    """
    _warn_deprecated()
    client = STClient()

    try:
        caps = client.list_capabilities()
    except APIError as e:
        handle_api_error(e)
        return

    output_capabilities(caps)


@app.command()
def show(
    capability_id: str,
) -> None:
    """Show capability details.

    Examples:
        st capability show login
    """
    _warn_deprecated()
    client = STClient()

    try:
        cap = client.get_capability(capability_id)
    except APIError as e:
        handle_api_error(e)
        return

    output_json(cap)


@app.command()
def create(
    capability_id: str,
    component: Annotated[str, typer.Option("--component", "-c")],
    name: Annotated[str | None, typer.Option("--name", "-n")] = None,
    description: Annotated[str | None, typer.Option("--description", "-d")] = None,
    priority: Annotated[int, typer.Option("--priority", "-p")] = 2,
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
    _warn_deprecated()
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
        handle_api_error(e)
        return

    output_json(cap)


@app.command()
def update(
    capability_id: str,
    name: Annotated[str | None, typer.Option("--name", "-n", help="Display name")] = None,
    description: Annotated[
        str | None, typer.Option("--description", "-d", help="Description")
    ] = None,
    priority: Annotated[
        int | None, typer.Option("--priority", "-p", min=0, max=4, help="Priority (0-4)")
    ] = None,
    status: Annotated[
        str | None, typer.Option("--status", "-s", help="Status (pending, active, deprecated)")
    ] = None,
) -> None:
    """Update a capability.

    Examples:
        st capability update user-login --name "User Authentication"
        st capability update user-login --priority 1
        st capability update user-login --status deprecated
    """
    _warn_deprecated()
    client = STClient()

    # Build update dict
    updates: dict = {}
    if name is not None:
        updates["name"] = name
    if description is not None:
        updates["description"] = description
    if priority is not None:
        updates["priority"] = priority
    if status is not None:
        updates["status"] = status

    if not updates:
        output_error("No updates specified")
        raise typer.Exit(1)

    try:
        cap = client.update_capability(capability_id, **updates)
    except APIError as e:
        handle_api_error(e)
        return

    output_json(cap)


@app.command()
def verify(
    capability_id: str,
) -> None:
    """Verify a capability's tests.

    Examples:
        st capability verify login
    """
    _warn_deprecated()
    client = STClient()

    try:
        result = client.verify_capability(capability_id)
    except APIError as e:
        handle_api_error(e)
        return

    output_json(result)
