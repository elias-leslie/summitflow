"""Docker stack commands through the existing system unit and container observations."""

from __future__ import annotations

import asyncio
import subprocess
from typing import Annotated

import typer

from app.api.docker.constants import COMPOSE_PROJECT, runtime_service_definitions
from app.api.docker.helpers import _infra_status
from app.utils import nightshift_stack

from ..runtime import compose_cmd, compose_cmd_for_mode, compose_env, read_docker_mode

app = typer.Typer(
    name="docker",
    help="Docker stack control for the SummitFlow ecosystem.",
    no_args_is_help=True,
)


@app.command()
def status() -> None:
    """Show actual container state using the same observations as Runtime."""
    typer.echo("DOCKER:STATUS")
    for svc in (svc for svc in runtime_service_definitions() if svc["manager"] == "docker"):
        row = asyncio.run(_infra_status(svc))
        typer.echo(f"  {svc['service']}:{row.state}:{','.join(svc['ports'])}")


def _compose(*args: str) -> None:
    raise typer.Exit(subprocess.run(args, env=compose_env(), check=False).returncode)


def _stack_action(action: str, service: str | None = None) -> None:
    if not nightshift_stack.stack_installed():
        if action == "start":
            _compose(*compose_cmd_for_mode(read_docker_mode(), "--profile", "summitflow"), "up", "-d")
        _compose(*(compose_cmd("down") if action == "stop" else compose_cmd("restart", *([service] if service else []))))
    result = nightshift_stack.request_stack(action)  # type: ignore[arg-type]
    if service:
        typer.echo(f"This controls the whole stack, including {service}.")
    typer.echo(result.message)
    raise typer.Exit(0 if result.success else 1)


@app.command()
def up() -> None:
    """Start the docker stack system unit."""
    _stack_action("start")


@app.command()
def down() -> None:
    """Stop the docker stack system unit."""
    _stack_action("stop")


@app.command()
def restart(
    service: Annotated[str | None, typer.Argument(help="Ignored: the whole stack restarts")] = None,
) -> None:
    """Restart the docker stack system unit."""
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
