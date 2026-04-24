"""Project service lifecycle commands."""

from __future__ import annotations

import time
from typing import Annotated

import typer

from ..lib import service_ops
from ..lib.confirm_token import confirm_gate
from ..output import output_error

app = typer.Typer(help="Project service lifecycle and rebuild commands")


def _load(project: str) -> service_ops.ProjectServices:
    try:
        return service_ops.load_project(project)
    except service_ops.ServiceError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None


@app.command()
def status(
    project: Annotated[
        str | None,
        typer.Argument(help="Project id. Omit to show all projects."),
    ] = None,
) -> None:
    """Show managed service status through the canonical service path."""
    projects = [project] if project else service_ops.project_ids()
    errors = 0
    for project_id in projects:
        services = _load(project_id)
        parts = []
        for svc in services.all_services:
            state = service_ops.service_state(svc)
            parts.append(f"{svc}:{state}")
            errors += state != "active"
        print(f"{services.project_id:<15} {' '.join(parts)}")
    raise typer.Exit(1 if errors else 0)


@app.command()
def rebuild(
    project: Annotated[str, typer.Argument(help="Project id to rebuild")],
    detach: Annotated[bool, typer.Option("--detach", help="Queue rebuild in background")] = False,
    include_all_workers: Annotated[
        bool,
        typer.Option("--include-all-workers", help="Restart protected optional workers too"),
    ] = False,
) -> None:
    """Build, migrate, restart, and health-check a project."""
    if detach:
        raise typer.Exit(service_ops.queue_detached(project, include_all_workers))
    services = _load(project)
    start_time = time.time()
    errors = 0
    print(f"Rebuilding {services.project_id}")
    errors += service_ops.ensure_infra() != 0
    errors += service_ops.build_frontend(services) != 0
    errors += service_ops.run_migrations(services) != 0
    if services.optional_workers and not include_all_workers:
        print(
            "[service] skipping protected workers: "
            + " ".join(services.optional_workers)
            + " (use --include-all-workers)"
        )
    service_ops.sync_systemd_units(services)
    if services.backend_service:
        errors += service_ops.restart_service(services.backend_service, port=services.backend_port) != 0
    for worker in services.workers(include_all=include_all_workers):
        errors += service_ops.restart_service(worker) != 0
    if services.frontend_service:
        errors += service_ops.restart_service(services.frontend_service, port=services.frontend_port) != 0
    errors += service_ops.verify_health(services)
    if errors == 0:
        service_ops.sync_seeds(services)
        print(f"[service] rebuild complete ({int(time.time() - start_time)}s)")
    else:
        print(f"[service] rebuild completed with {errors} error(s)")
    raise typer.Exit(1 if errors else 0)


@app.command()
def restart(
    project: Annotated[str, typer.Argument(help="Project id to restart/rebuild")],
    detach: Annotated[bool, typer.Option("--detach", help="Queue restart in background")] = False,
    include_all_workers: Annotated[
        bool,
        typer.Option("--include-all-workers", help="Restart protected optional workers too"),
    ] = False,
) -> None:
    """Restart a managed project through the rebuild path."""
    rebuild(project, detach=detach, include_all_workers=include_all_workers)


@app.command()
def start(
    project: Annotated[str, typer.Argument(help="Project id to start")] = "summitflow",
) -> None:
    """Start a managed project's service set."""
    raise typer.Exit(service_ops.start_services(_load(project)))


@app.command()
def stop(
    project: Annotated[str, typer.Argument(help="Project id to stop")] = "summitflow",
    confirm: Annotated[str | None, typer.Option("--confirm", help="Confirm token from preview run")] = None,
) -> None:
    """Stop a managed project's service set. Two-pass confirmation required."""
    services = _load(project)
    confirm_gate(
        f"service-stop-{services.project_id}",
        confirm,
        [
            f"STOP SERVICES: {services.project_id}",
            "This interrupts active local sessions for that project.",
            "Services: " + ", ".join(services.all_services),
        ],
        f"st service stop {services.project_id}",
    )
    raise typer.Exit(service_ops.stop_services(services))
