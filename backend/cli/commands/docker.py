"""Docker stack commands for the SummitFlow ecosystem.

The stack is the root unit ``summitflow-stack.service``; SummitFlow has no docker
rights, so start/stop/restart go through Nightshift's typed unit actions and
status is a port probe. Until that unit is installed, up/down/restart/logs keep
using docker compose as before.
"""

from __future__ import annotations

import socket
import subprocess
from typing import Annotated

import typer
from typer.main import get_command

from app.api.docker.constants import COMPOSE_PROJECT, runtime_service_definitions
from app.utils import nightshift_stack

from ..runtime import compose_cmd, compose_cmd_for_mode, compose_env, read_docker_mode

app = typer.Typer(
    name="docker",
    help="Docker stack control for the SummitFlow ecosystem (through Nightshift).",
    no_args_is_help=True,
)


def _port_open(port: str) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.75):
            return True
    except (OSError, ValueError):
        return False


@app.command()
def status() -> None:
    """Show which stack services answer on their ports."""
    typer.echo("DOCKER:STATUS")
    for svc in (svc for svc in runtime_service_definitions() if svc["manager"] == "docker"):
        up = all(_port_open(port) for port in svc["ports"])
        typer.echo(f"  {svc['service']}:{'running' if up else 'stopped'}:{','.join(svc['ports'])}")


def _compose(*args: str) -> None:
    raise typer.Exit(subprocess.run(args, env=compose_env(), check=False).returncode)


def _stack_action(action: str, service: str | None = None) -> None:
    if not nightshift_stack.stack_installed():
        if action == "start":
            _compose(*compose_cmd_for_mode(read_docker_mode(), "--profile", "summitflow"), "up", "-d")
        _compose(*(compose_cmd("down") if action == "stop" else compose_cmd("restart", *([service] if service else []))))
    result = nightshift_stack.request_stack(action)  # type: ignore[arg-type]
    if service:
        typer.echo(f"Nightshift has one action for the whole stack, so {service} is not handled alone.")
    typer.echo(result.message)
    raise typer.Exit(0 if result.success else 1)


@app.command()
def up() -> None:
    """Start the docker stack (Nightshift unit.start)."""
    _stack_action("start")


@app.command()
def down() -> None:
    """Stop the docker stack (Nightshift unit.stop)."""
    _stack_action("stop")


@app.command()
def restart(
    service: Annotated[str | None, typer.Argument(help="Ignored: the whole stack restarts")] = None,
) -> None:
    """Restart the docker stack (Nightshift unit.restart)."""
    _stack_action("restart", service)


@app.command()
def logs(
    service: Annotated[str, typer.Argument(help="Service name")],
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Follow log output")] = False,
    tail: Annotated[int, typer.Option("--tail", "-n", help="Number of lines to show")] = 50,
) -> None:
    """Show container logs from journald."""
    if not nightshift_stack.stack_installed():
        _compose(*compose_cmd("logs", "--tail", str(tail), *(["-f"] if follow else []), service))
    args = ["journalctl", f"CONTAINER_NAME={COMPOSE_PROJECT}-{service}-1", "-n", str(tail), "--no-pager", "--output=short-iso"]
    if follow:
        args.append("-f")
    raise typer.Exit(subprocess.run(args, check=False).returncode)


@app.command()
def backup(
    note: Annotated[str, typer.Option("--note", help="Backup note/description")] = "",
) -> None:
    """Create an infrastructure backup via the unified backup system.

    Equivalent to: st backup infra create
    """
    typer.echo("Delegating to unified backup system...")
    typer.echo("Tip: Use 'st backup infra create' directly for full options.\n")

    from ..output_context import OutputContext
    from .backup_infra import create_infra_backup as _create

    ctx = typer.Context(get_command(app), obj=OutputContext())
    _create(ctx, note=note or None, keep_local=False)


@app.command()
def restore(
    backup_id: Annotated[
        str, typer.Argument(help="Backup ID to restore (from 'st backup infra list')"),
    ],
) -> None:
    """Restore from an infrastructure backup.

    Equivalent to: st backup restore <id> --source infrastructure
    """
    typer.echo("Delegating to unified backup system...")
    typer.echo("Tip: Use 'st backup restore <id> --source infrastructure' directly.\n")

    from ..output_context import OutputContext
    from .backup import restore_backup as _restore

    ctx = typer.Context(get_command(app), obj=OutputContext())
    _restore(ctx, backup_id=backup_id, dry_run=False, source="infrastructure")
