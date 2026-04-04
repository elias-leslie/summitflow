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

from ..runtime import (
    COMPOSE_ENV_FILE,
    COMPOSE_FILE,
    compose_cmd,
    compose_cmd_for_mode,
    compose_env,
    read_docker_mode,
    write_docker_mode,
)

app = typer.Typer(
    name="docker",
    help="Docker container management for the SummitFlow ecosystem.",
    no_args_is_help=True,
)

# ─── Constants ───────────────────────────────────────────────────

ENV_PREFIX = "stenv-"

_BUILD_PROJECTS = [
    ("summitflow",  "docker/backend.Dockerfile",  "ghcr.io/summitflow-solutions/summitflow-api"),
    ("summitflow",  "docker/frontend.Dockerfile", "ghcr.io/summitflow-solutions/summitflow-web"),
    ("summitflow",  "docker/agent-browser.Dockerfile", "ghcr.io/summitflow-solutions/agent-browser"),
    ("agent-hub",   "docker/backend.Dockerfile",  "ghcr.io/summitflow-solutions/agent-hub-api"),
    ("agent-hub",   "docker/frontend.Dockerfile", "ghcr.io/summitflow-solutions/agent-hub-web"),
    ("terminal",    "docker/backend.Dockerfile",  "ghcr.io/summitflow-solutions/terminal-api"),
    ("terminal",    "docker/frontend.Dockerfile", "ghcr.io/summitflow-solutions/terminal-web"),
    ("portfolio-ai","docker/backend.Dockerfile",  "ghcr.io/summitflow-solutions/portfolio-api"),
    ("portfolio-ai","docker/frontend.Dockerfile", "ghcr.io/summitflow-solutions/portfolio-web"),
    ("monkey-fight","Dockerfile",                 "ghcr.io/summitflow-solutions/monkey-fight"),
]

# ─── Helpers ─────────────────────────────────────────────────────


def _run(
    args: list[str],
    *,
    capture: bool = False,
    stream: bool = False,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str] | None:
    """Run a subprocess, optionally capturing or streaming output."""
    if stream:
        proc = subprocess.Popen(args, stdout=sys.stdout, stderr=sys.stderr, env=env)
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
        if check and proc.returncode not in (0, None):
            raise typer.Exit(proc.returncode)
        return None

    result = subprocess.run(args, capture_output=capture, text=True, env=env)
    if check and result.returncode != 0:
        if capture and result.stderr:
            typer.echo(result.stderr, err=True)
        raise typer.Exit(result.returncode)
    return result


def _parse_json_lines(text: str) -> list[dict]:
    """Parse newline-delimited JSON, skipping invalid lines. Handles arrays and objects."""
    if not text.strip():
        return []
    rows: list[dict] = []
    for line in text.strip().splitlines():
        try:
            data = json.loads(line)
            if isinstance(data, list):
                rows.extend(data)
            else:
                rows.append(data)
        except json.JSONDecodeError:
            continue
    return rows


def _compose_json(*args: str) -> list[dict]:
    """Run a docker compose command that returns JSON lines."""
    result = _run(
        compose_cmd(*args, "--format", "json"),
        capture=True,
        check=False,
        env=compose_env(),
    )
    return _parse_json_lines(result.stdout if result else "")


def _list_envs() -> list[dict]:
    """Return active ephemeral test environments (stenv-* projects)."""
    result = _run(
        ["docker", "compose", "ls", "--format", "json"],
        capture=True,
        check=False,
    )
    rows = _parse_json_lines(result.stdout if result else "")
    return [r for r in rows if r.get("Name", "").startswith(ENV_PREFIX)]


def _env_compose_cmd(project_name: str, *args: str) -> list[str]:
    """Build a docker compose command targeting an ephemeral environment."""
    return ["docker", "compose", "--env-file", str(COMPOSE_ENV_FILE), "-p", project_name, *args]


def _resolve_project_context(project: str) -> Path | None:
    """Resolve a repo checkout for a buildable project.

    Prefer sibling repos relative to the current SummitFlow checkout, then fall
    back to historical `$HOME/<project>` paths that exist on older setups.
    """
    summitflow_root = Path(__file__).resolve().parents[3]
    sibling_root = summitflow_root.parent
    candidates = [
        sibling_root / project,
        Path.home() / project,
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


# ─── Status ──────────────────────────────────────────────────────


@app.command()
def status() -> None:
    """Show container health grid (TOON format)."""
    containers = _compose_json("ps", "--all")
    mode = read_docker_mode()
    typer.echo(f"DOCKER:MODE:{mode}")
    typer.echo("DOCKER:STATUS")
    if not containers:
        typer.echo("  (no containers running)")
        return
    for c in containers:
        name = c.get("Name", c.get("Service", "unknown"))
        state = c.get("State", "unknown")
        health = c.get("Health", "")
        status_str = c.get("Status", "")
        published = {str(p["PublishedPort"]) for p in c.get("Publishers", []) if p.get("PublishedPort")}
        port_str = f":{','.join(published)}" if published else ""
        typer.echo(f"  {name}:{health or state}{port_str}:{status_str}")


# ─── Lifecycle ───────────────────────────────────────────────────


@app.command()
def up(
    profile: Annotated[
        str, typer.Option("--profile", "-p", help="Compose profile to start"),
    ] = "summitflow",
    dev: Annotated[
        bool, typer.Option("--dev", help="Use development override (bind mounts + hot reload)"),
    ] = False,
    prod: Annotated[
        bool, typer.Option("--prod", help="Use production runtime images"),
    ] = False,
    detach: Annotated[
        bool, typer.Option("--detach/--no-detach", "-d", help="Run in background"),
    ] = True,
) -> None:
    """Start the Docker compose stack."""
    if dev and prod:
        raise typer.BadParameter("Choose either --dev or --prod, not both.")
    mode = "dev" if dev else "prod" if prod else read_docker_mode()
    write_docker_mode(mode)
    args = compose_cmd_for_mode(mode, "--profile", profile)
    args.extend(["up"])
    if detach:
        args.append("-d")
    _run(args, stream=True, env=compose_env())


@app.command()
def down(
    volumes: Annotated[
        bool, typer.Option("--volumes", "-v", help="Remove named volumes (destroys data!)"),
    ] = False,
    confirm: Annotated[
        str | None, typer.Option("--confirm", help="Confirm token from preview run (required with --volumes)"),
    ] = None,
) -> None:
    """Stop the Docker compose stack.

    When --volumes is used, two-pass confirmation is required.
    """
    args = compose_cmd("down")
    if volumes:
        from ..lib.confirm_token import confirm_gate

        confirm_gate(
            "docker-down-volumes",
            confirm,
            [
                "DOCKER DOWN --volumes will:",
                "  Stop all containers in the compose stack",
                "  DESTROY all named volumes (PostgreSQL, Redis, Hatchet data)",
                "",
                "This permanently deletes all database contents and cached state.",
            ],
            "st docker down --volumes",
        )
        args.append("--volumes")
    _run(args, stream=True, env=compose_env())


@app.command()
def restart(
    service: Annotated[
        str | None, typer.Argument(help="Service to restart (all if omitted)"),
    ] = None,
    recreate: Annotated[
        bool, typer.Option("--recreate", help="Force-recreate container from current image"),
    ] = False,
) -> None:
    """Restart one or all containers.

    Use --recreate to rebuild and recreate containers from the current image
    (equivalent to docker compose up --force-recreate --build).
    """
    args = compose_cmd("up", "-d", "--force-recreate", "--build") if recreate else compose_cmd("restart")
    if service:
        args.append(service)
    _run(args, stream=True, env=compose_env())


# ─── Logs ────────────────────────────────────────────────────────


@app.command()
def logs(
    service: Annotated[str, typer.Argument(help="Service name")],
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Follow log output")] = False,
    tail: Annotated[int, typer.Option("--tail", "-n", help="Number of lines to show")] = 50,
) -> None:
    """Tail container logs."""
    args = compose_cmd("logs", "--tail", str(tail))
    if follow:
        args.append("-f")
    args.append(service)
    _run(args, stream=True, env=compose_env())


# ─── Build & Pull ───────────────────────────────────────────────


@app.command()
def build(
    push: Annotated[bool, typer.Option("--push", help="Push images after building")] = False,
    tag: Annotated[str, typer.Option("--tag", "-t", help="Image tag")] = "latest",
) -> None:
    """Build Docker images for all services."""
    typer.echo(f"Building images with tag: {tag}")
    for project, dockerfile, image_base in _BUILD_PROJECTS:
        image = f"{image_base}:{tag}"
        context = _resolve_project_context(project)
        if context is None:
            typer.echo(f"  SKIP {image} (project checkout not found)")
            continue
        df_path = context / dockerfile
        if not df_path.exists():
            typer.echo(f"  SKIP {image} (Dockerfile not found)")
            continue
        typer.echo(f"  BUILD {image}")
        _run(["docker", "build", "-f", str(df_path), "-t", image, str(context)], stream=True)
        if push:
            typer.echo(f"  PUSH {image}")
            _run(["docker", "push", image], stream=True)


@app.command()
def pull() -> None:
    """Pull latest images for all services."""
    _run(compose_cmd("pull"), stream=True, env=compose_env())


# ─── Shell ───────────────────────────────────────────────────────


@app.command()
def shell(
    service: Annotated[str, typer.Argument(help="Service name")],
) -> None:
    """Open an interactive shell in a running container."""
    _run(compose_cmd("exec", service, "/bin/bash"), stream=True, check=False, env=compose_env())


# ─── Backup & Restore (delegated to unified backup system) ──────


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

    ctx = typer.Context(app, obj=OutputContext())
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

    ctx = typer.Context(app, obj=OutputContext())
    _restore(ctx, backup_id=backup_id, dry_run=False, source="infrastructure")


# ─── Ephemeral Test Environments ─────────────────────────────────


@app.command("env-create")
def env_create(
    name: Annotated[str, typer.Argument(help="Environment name")],
    profile: Annotated[str, typer.Option("--profile", "-p", help="Compose profile")] = "summitflow",
    with_browser: Annotated[
        bool, typer.Option("--with-browser", help="Include agent-browser container"),
    ] = False,
) -> None:
    """Create an ephemeral test environment."""
    project_name = f"{ENV_PREFIX}{name}"
    args = _env_compose_cmd(project_name, "-f", str(COMPOSE_FILE), "--profile", profile)
    if with_browser:
        args.extend(["--profile", "browser"])
    args.extend(["up", "-d"])
    typer.echo(f"Creating test environment: {name} (profile: {profile})")
    _run(args, stream=True, env=compose_env())


@app.command("env-list")
def env_list() -> None:
    """List active test environments."""
    envs = _list_envs()
    if not envs:
        typer.echo("No test environments found.")
        return
    for env in envs:
        name = env.get("Name", "").removeprefix(ENV_PREFIX)
        typer.echo(f"  {name}: {env.get('Status', 'unknown')}")


@app.command("env-destroy")
def env_destroy(
    name: Annotated[
        str | None, typer.Argument(help="Environment name (omit for --all)"),
    ] = None,
    all_envs: Annotated[
        bool, typer.Option("--all", help="Destroy all test environments"),
    ] = False,
) -> None:
    """Tear down a test environment."""
    if not all_envs and not name:
        typer.echo("Provide environment name or use --all", err=True)
        raise typer.Exit(1)

    targets = [env["Name"] for env in _list_envs()] if all_envs else [f"{ENV_PREFIX}{name}"]
    for project_name in targets:
        typer.echo(f"Destroying: {project_name}")
        _run(
            _env_compose_cmd(project_name, "down", "--volumes"),
            stream=True,
            check=False,
            env=compose_env(),
        )


@app.command("env-exec")
def env_exec(
    name: Annotated[str, typer.Argument(help="Environment name")],
    cmd: Annotated[list[str], typer.Argument(help="Command to run")],
) -> None:
    """Run a command in a test environment service."""
    if not cmd:
        typer.echo("Provide a command to run", err=True)
        raise typer.Exit(1)
    project_name = f"{ENV_PREFIX}{name}"
    _run(_env_compose_cmd(project_name, "exec", *cmd), stream=True, check=False, env=compose_env())


# ─── Metrics ─────────────────────────────────────────────────────


@app.command()
def metrics() -> None:
    """Show CPU/memory per container."""
    result = _run(
        ["docker", "stats", "--no-stream", "--format", "json"],
        capture=True,
        check=False,
    )
    rows = _parse_json_lines(result.stdout if result else "")
    if not rows:
        typer.echo("No running containers.")
        return
    typer.echo("DOCKER:METRICS")
    typer.echo(f"  {'NAME':<30} {'CPU':>8} {'MEM':>12} {'MEM %':>8}")
    typer.echo(f"  {'─' * 30} {'─' * 8} {'─' * 12} {'─' * 8}")
    for c in rows:
        typer.echo(
            f"  {c.get('Name', 'unknown'):<30} {c.get('CPUPerc', '0%'):>8} "
            f"{c.get('MemUsage', '0B / 0B'):>12} {c.get('MemPerc', '0%'):>8}"
        )
