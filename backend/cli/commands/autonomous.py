"""Autonomous execution commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..lib.usage import usage
from ..output import handle_api_error, output_json

app = typer.Typer(help="Autonomous execution management")


@app.command()
@usage(
    surface="st.autonomous.status",
    cmd="st autonomous status",
    when="inspect autonomous execution permission and project settings",
    task_types=("devops", "verification"),
)
def status() -> None:
    """Show autonomous execution settings for the project.

    Examples:
        st autonomous status
    """
    client = STClient()

    try:
        result = client.get_autonomous_settings()
    except APIError as e:
        handle_api_error(e)
        return

    output_json(result)


@app.command()
@usage(
    surface="st.autonomous.enable",
    cmd="st autonomous enable",
    when="enable autonomous project execution and scheduled work pickup",
    precautions=("syncs SummitFlow settings, Agent Hub execution permission, and work-pickup schedules",),
    task_types=("devops",),
)
def enable(
    work_pickup: Annotated[
        bool,
        typer.Option(
            "--work-pickup/--no-work-pickup",
            help="Enable scheduled autonomous work pickup with execution permission.",
        ),
    ] = True,
    upkeep: Annotated[
        bool,
        typer.Option(
            "--upkeep/--no-upkeep",
            help="Enable routine upkeep discovery and its schedule.",
        ),
    ] = True,
) -> None:
    """Enable autonomous execution for the project.

    Examples:
        st autonomous enable
        st autonomous enable --no-upkeep
    """
    client = STClient()

    try:
        result = client.update_autonomous_settings(enabled=True, upkeep_enabled=upkeep)
        schedules = [
            client.update_autonomous_schedule("work_pickup", enabled=work_pickup),
            client.update_autonomous_schedule("task_generation", enabled=upkeep),
        ]
    except APIError as e:
        handle_api_error(e)
        return

    result["schedules"] = schedules
    output_json(result)


@app.command()
@usage(
    surface="st.autonomous.disable",
    cmd="st autonomous disable",
    when="disable autonomous execution and scheduled work pickup",
    precautions=("also disables work pickup; routine upkeep schedule is left configurable with --keep-upkeep",),
    task_types=("devops",),
)
def disable(
    keep_upkeep: Annotated[
        bool,
        typer.Option(
            "--keep-upkeep/--disable-upkeep",
            help="Keep routine upkeep discovery enabled while stopping autonomous execution.",
        ),
    ] = True,
) -> None:
    """Disable autonomous execution for the project.

    Examples:
        st autonomous disable
        st autonomous disable --disable-upkeep
    """
    client = STClient()

    try:
        result = client.update_autonomous_settings(enabled=False)
        schedules = [client.update_autonomous_schedule("work_pickup", enabled=False)]
        if not keep_upkeep:
            result = client.update_autonomous_settings(enabled=False, upkeep_enabled=False)
            schedules.append(client.update_autonomous_schedule("task_generation", enabled=False))
    except APIError as e:
        handle_api_error(e)
        return

    result["schedules"] = schedules
    output_json(result)


@app.command()
@usage(
    surface="st.autonomous.schedules",
    cmd="st autonomous schedules",
    when="inspect autonomous schedule enablement for the current project",
    task_types=("devops", "verification"),
)
def schedules() -> None:
    """List autonomous schedule states for the project."""
    client = STClient()

    try:
        result = client.list_autonomous_schedules()
    except APIError as e:
        handle_api_error(e)
        return

    output_json(result)
