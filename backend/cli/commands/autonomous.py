"""Autonomous execution commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..lib.usage import usage
from ..output import handle_api_error, output_error, output_json

app = typer.Typer(help="Autonomous execution management")


@app.command()
@usage(
    surface="st.autonomous.status",
    cmd="st autonomous status",
    when="inspect Agent Hub execution permission and find canonical automation policy/profile read commands",
    task_types=("autonomous", "upkeep", "heartbeat",),
    on_demand="autonomous operations",
)
def status() -> None:
    """Show the execution permission gate and canonical automation read paths.

    Examples:
        st autonomous status
    """
    client = STClient()

    try:
        result = client.get_autonomous_settings()
    except APIError as e:
        handle_api_error(e)
        return

    project_id = client.project_id
    output_json(
        {
            "project_id": project_id,
            "execution_permission": {
                "source": "agent_hub_project_permission",
                "auto_exec_enabled": result.get("enabled"),
                "execution_allowed": result.get("execution_allowed"),
                "execution_in_time_window": result.get("execution_in_time_window"),
                "permission_tier": result.get("permission_tier"),
                "permission_reason": result.get("permission_reason"),
            },
            "automations": {
                "policy": f"st automations policy {project_id}",
                "profiles": f"st automations list --project {project_id}",
            },
        }
    )


@app.command(hidden=True)
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
    """Legacy command retained only to direct callers to Agent Hub."""
    output_error(
        "Automation controls moved to Agent Hub. Use st automations list --project PROJECT, "
        "st automations policy PROJECT, then st automations enable/disable PROFILE_ID --revision N "
        "or st automations policy-apply PROJECT --file POLICY.json."
    )
    raise typer.Exit(2)


@app.command(hidden=True)
def disable(
    keep_upkeep: Annotated[
        bool,
        typer.Option(
            "--keep-upkeep/--disable-upkeep",
            help="Keep routine upkeep discovery enabled while stopping autonomous execution.",
        ),
    ] = True,
) -> None:
    """Legacy command retained only to direct callers to Agent Hub."""
    output_error(
        "Automation controls moved to Agent Hub. Use st automations list --project PROJECT, "
        "st automations policy PROJECT, then st automations enable/disable PROFILE_ID --revision N "
        "or st automations policy-apply PROJECT --file POLICY.json."
    )
    raise typer.Exit(2)


@app.command()
@usage(
    surface="st.autonomous.schedules",
    cmd="st autonomous schedules",
    when="inspect SummitFlow-owned system schedules; use st automations list for Agent Hub workflows",
    task_types=("devops",),
    on_demand="autonomous operations",
)
def schedules() -> None:
    """List SummitFlow-owned schedules; Agent Hub profiles are listed centrally."""
    client = STClient()

    try:
        result = client.list_autonomous_schedules()
    except APIError as e:
        handle_api_error(e)
        return

    output_json(result)


@app.command()
@usage(
    surface="st.autonomous.upkeep",
    cmd="st autonomous upkeep",
    when="run one routine upkeep discovery cycle for the current project",
    task_types=("autonomous", "upkeep", "heartbeat",),
    on_demand="autonomous operations",
)
def upkeep() -> None:
    """Run one routine upkeep discovery cycle now."""
    client = STClient()

    try:
        result = client.run_routine_upkeep()
    except APIError as e:
        handle_api_error(e)
        return

    output_json(result)
