"""Docker management commands for the SummitFlow ecosystem.

Provides `st docker` subcommands for container lifecycle, logs, backup/restore,
ephemeral test environments, and metrics.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from ..runtime import COMPOSE_DIR, COMPOSE_FILE, compose_cmd

app = typer.Typer(
    name="docker",
    help="Docker container management for the SummitFlow ecosystem.",
    no_args_is_help=True,
)

# ─── Helpers ─────────────────────────────────────────────────────


def _run(
    args: list[str],
    *,
    capture: bool = False,
    stream: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str] | None:
    """Run a subprocess, optionally capturing or streaming output."""
    if stream:
        proc = subprocess.Popen(args, stdout=sys.stdout, stderr=sys.stderr)
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
        return None

    result = subprocess.run(args, capture_output=capture, text=True)
    if check and result.returncode != 0:
        if capture and result.stderr:
            typer.echo(result.stderr, err=True)
        raise typer.Exit(result.returncode)
    return result


def _compose_json(
    *args: str,
) -> list[dict]:
    """Run a docker compose command that returns JSON lines."""
    result = _run(compose_cmd(*args, "--format", "json"), capture=True, check=False)
    if not result or not result.stdout.strip():
        return []
    lines = []
    for line in result.stdout.strip().splitlines():
        try:
            lines.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return lines


# ─── Status ──────────────────────────────────────────────────────


@app.command()
def status() -> None:
    """Show container health grid (TOON format)."""
    containers = _compose_json("ps", "--all")
    if not containers:
        typer.echo("DOCKER:STATUS\n  (no containers running)")
        return

    typer.echo("DOCKER:STATUS")
    for c in containers:
        name = c.get("Name", c.get("Service", "unknown"))
        state = c.get("State", "unknown")
        health = c.get("Health", "")
        status_str = c.get("Status", "")

        # Extract port bindings
        ports = c.get("Publishers", [])
        port_str = ""
        if ports:
            published = [str(p.get("PublishedPort", "")) for p in ports if p.get("PublishedPort")]
            if published:
                port_str = f":{','.join(set(published))}"

        display_health = health if health else state
        typer.echo(f"  {name}:{display_health}{port_str}:{status_str}")


# ─── Lifecycle ───────────────────────────────────────────────────


@app.command()
def up(
    profile: Annotated[
        str,
        typer.Option("--profile", "-p", help="Compose profile to start"),
    ] = "summitflow",
    dev: Annotated[
        bool,
        typer.Option("--dev", help="Use development override (bind mounts + hot reload)"),
    ] = False,
    detach: Annotated[
        bool,
        typer.Option("--detach/--no-detach", "-d", help="Run in background"),
    ] = True,
) -> None:
    """Start the Docker compose stack."""
    args = compose_cmd("--profile", profile)
    if dev:
        dev_file = COMPOSE_DIR / "docker-compose.dev.yml"
        if dev_file.exists():
            args = compose_cmd("-f", str(COMPOSE_FILE), "-f", str(dev_file), "--profile", profile)
    args.extend(["up"])
    if detach:
        args.append("-d")
    _run(args, stream=True)


@app.command()
def down(
    volumes: Annotated[
        bool,
        typer.Option("--volumes", "-v", help="Remove named volumes (destroys data!)"),
    ] = False,
) -> None:
    """Stop the Docker compose stack."""
    args = compose_cmd("down")
    if volumes:
        confirm = typer.confirm("This will destroy all data volumes. Continue?")
        if not confirm:
            raise typer.Abort()
        args.append("--volumes")
    _run(args, stream=True)


@app.command()
def restart(
    service: Annotated[
        str | None,
        typer.Argument(help="Service to restart (all if omitted)"),
    ] = None,
) -> None:
    """Restart one or all containers."""
    args = compose_cmd("restart")
    if service:
        args.append(service)
    _run(args, stream=True)


# ─── Logs ────────────────────────────────────────────────────────


@app.command()
def logs(
    service: Annotated[
        str,
        typer.Argument(help="Service name"),
    ],
    follow: Annotated[
        bool,
        typer.Option("--follow", "-f", help="Follow log output"),
    ] = False,
    tail: Annotated[
        int,
        typer.Option("--tail", "-n", help="Number of lines to show"),
    ] = 50,
) -> None:
    """Tail container logs."""
    args = compose_cmd("logs", "--tail", str(tail))
    if follow:
        args.append("-f")
    args.append(service)
    _run(args, stream=True)


# ─── Build & Pull ───────────────────────────────────────────────


@app.command()
def build(
    push: Annotated[
        bool,
        typer.Option("--push", help="Push images after building"),
    ] = False,
    tag: Annotated[
        str,
        typer.Option("--tag", "-t", help="Image tag"),
    ] = "latest",
) -> None:
    """Build Docker images for all services."""
    typer.echo(f"Building images with tag: {tag}")

    # Build each project's Dockerfiles
    projects = [
        ("summitflow", "docker/backend.Dockerfile", f"ghcr.io/summitflow-solutions/summitflow-api:{tag}"),
        ("summitflow", "docker/frontend.Dockerfile", f"ghcr.io/summitflow-solutions/summitflow-web:{tag}"),
        ("agent-hub", "docker/backend.Dockerfile", f"ghcr.io/summitflow-solutions/agent-hub-api:{tag}"),
        ("agent-hub", "docker/frontend.Dockerfile", f"ghcr.io/summitflow-solutions/agent-hub-web:{tag}"),
        ("terminal", "docker/backend.Dockerfile", f"ghcr.io/summitflow-solutions/terminal-api:{tag}"),
        ("terminal", "docker/frontend.Dockerfile", f"ghcr.io/summitflow-solutions/terminal-web:{tag}"),
        ("portfolio-ai", "docker/backend.Dockerfile", f"ghcr.io/summitflow-solutions/portfolio-api:{tag}"),
        ("portfolio-ai", "docker/frontend.Dockerfile", f"ghcr.io/summitflow-solutions/portfolio-web:{tag}"),
        ("monkey-fight", "docker/Dockerfile", f"ghcr.io/summitflow-solutions/monkey-fight:{tag}"),
    ]

    home = Path.home()
    for project, dockerfile, image in projects:
        context = home / project
        df_path = context / dockerfile
        if not df_path.exists():
            typer.echo(f"  SKIP {image} (Dockerfile not found)")
            continue
        typer.echo(f"  BUILD {image}")
        _run(
            ["docker", "build", "-f", str(df_path), "-t", image, str(context)],
            stream=True,
        )
        if push:
            typer.echo(f"  PUSH {image}")
            _run(["docker", "push", image], stream=True)


@app.command()
def pull() -> None:
    """Pull latest images for all services."""
    _run(compose_cmd("pull"), stream=True)


# ─── Shell ───────────────────────────────────────────────────────


@app.command()
def shell(
    service: Annotated[
        str,
        typer.Argument(help="Service name"),
    ],
) -> None:
    """Open an interactive shell in a running container."""
    _run(
        compose_cmd("exec", service, "/bin/bash"),
        stream=True,
        check=False,
    )


# ─── Backup & Restore (delegated to unified backup system) ──────

@app.command()
def backup(
    note: Annotated[
        str,
        typer.Option("--note", help="Backup note/description"),
    ] = "",
) -> None:
    """Create an infrastructure backup via the unified backup system.

    Equivalent to: st backup infra create
    """
    typer.echo("Delegating to unified backup system...")
    typer.echo("Tip: Use 'st backup infra create' directly for full options.\n")

    from ..output_context import OutputContext
    from .backup_infra import create_infra_backup as _create

    ctx = typer.Context(app, obj=OutputContext())
    _create(ctx, note=note or None, keep_local=False)


@app.command()
def restore(
    backup_id: Annotated[
        str,
        typer.Argument(help="Backup ID to restore (from 'st backup infra list')"),
    ],
) -> None:
    """Restore from an infrastructure backup.

    Equivalent to: st backup restore <id> --source infrastructure
    """
    typer.echo("Delegating to unified backup system...")
    typer.echo("Tip: Use 'st backup restore <id> --source infrastructure' directly.\n")

    from ..output_context import OutputContext
    from .backup import restore_backup as _restore

    ctx = typer.Context(app, obj=OutputContext())
    _restore(ctx, backup_id=backup_id, dry_run=False, source="infrastructure")


# ─── Ephemeral Test Environments ─────────────────────────────────

ENV_PREFIX = "stenv-"


@app.command("env-create")
def env_create(
    name: Annotated[str, typer.Argument(help="Environment name")],
    profile: Annotated[
        str,
        typer.Option("--profile", "-p", help="Compose profile"),
    ] = "summitflow",
    with_browser: Annotated[
        bool,
        typer.Option("--with-browser", help="Include agent-browser container"),
    ] = False,
) -> None:
    """Create an ephemeral test environment."""
    project_name = f"{ENV_PREFIX}{name}"
    args = [
        "docker",
        "compose",
        "-f",
        str(COMPOSE_FILE),
        "-p",
        project_name,
        "--profile",
        profile,
    ]
    if with_browser:
        args.extend(["--profile", "browser"])
    args.extend(["up", "-d"])
    typer.echo(f"Creating test environment: {name} (profile: {profile})")
    _run(args, stream=True)


@app.command("env-list")
def env_list() -> None:
    """List active test environments."""
    result = _run(
        ["docker", "compose", "ls", "--format", "json"],
        capture=True,
        check=False,
    )
    if not result or not result.stdout.strip():
        typer.echo("No test environments found.")
        return

    envs = []
    for line in result.stdout.strip().splitlines():
        try:
            data = json.loads(line)
            if isinstance(data, list):
                envs.extend(data)
            else:
                envs.append(data)
        except json.JSONDecodeError:
            continue

    found = False
    for env in envs:
        name = env.get("Name", "")
        if name.startswith(ENV_PREFIX):
            status_str = env.get("Status", "unknown")
            typer.echo(f"  {name.removeprefix(ENV_PREFIX)}: {status_str}")
            found = True

    if not found:
        typer.echo("No test environments found.")


@app.command("env-destroy")
def env_destroy(
    name: Annotated[
        str | None,
        typer.Argument(help="Environment name (omit for --all)"),
    ] = None,
    all_envs: Annotated[
        bool,
        typer.Option("--all", help="Destroy all test environments"),
    ] = False,
) -> None:
    """Tear down a test environment."""
    if all_envs:
        # List and destroy all stenv- projects
        result = _run(
            ["docker", "compose", "ls", "--format", "json"],
            capture=True,
            check=False,
        )
        if result and result.stdout.strip():
            for line in result.stdout.strip().splitlines():
                try:
                    data = json.loads(line)
                    items = data if isinstance(data, list) else [data]
                    for env in items:
                        env_name = env.get("Name", "")
                        if env_name.startswith(ENV_PREFIX):
                            typer.echo(f"Destroying: {env_name}")
                            _run(
                                ["docker", "compose", "-p", env_name, "down", "--volumes"],
                                stream=True,
                                check=False,
                            )
                except json.JSONDecodeError:
                    continue
        return

    if not name:
        typer.echo("Provide environment name or use --all", err=True)
        raise typer.Exit(1)

    project_name = f"{ENV_PREFIX}{name}"
    typer.echo(f"Destroying test environment: {name}")
    _run(
        ["docker", "compose", "-p", project_name, "down", "--volumes"],
        stream=True,
    )


@app.command("env-exec")
def env_exec(
    name: Annotated[str, typer.Argument(help="Environment name")],
    cmd: Annotated[list[str], typer.Argument(help="Command to run")],
) -> None:
    """Run a command in a test environment service."""
    project_name = f"{ENV_PREFIX}{name}"
    if not cmd:
        typer.echo("Provide a command to run", err=True)
        raise typer.Exit(1)
    _run(
        ["docker", "compose", "-p", project_name, "exec", *cmd],
        stream=True,
        check=False,
    )


# ─── Metrics ─────────────────────────────────────────────────────


@app.command()
def metrics() -> None:
    """Show CPU/memory per container."""
    result = _run(
        ["docker", "stats", "--no-stream", "--format", "json"],
        capture=True,
        check=False,
    )
    if not result or not result.stdout.strip():
        typer.echo("No running containers.")
        return

    typer.echo("DOCKER:METRICS")
    typer.echo(f"  {'NAME':<30} {'CPU':>8} {'MEM':>12} {'MEM %':>8}")
    typer.echo(f"  {'─' * 30} {'─' * 8} {'─' * 12} {'─' * 8}")
    for line in result.stdout.strip().splitlines():
        try:
            c = json.loads(line)
            name = c.get("Name", "unknown")
            cpu = c.get("CPUPerc", "0%")
            mem = c.get("MemUsage", "0B / 0B")
            mem_pct = c.get("MemPerc", "0%")
            typer.echo(f"  {name:<30} {cpu:>8} {mem:>12} {mem_pct:>8}")
        except json.JSONDecodeError:
            continue
