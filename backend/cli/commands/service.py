"""Project service lifecycle commands."""

from __future__ import annotations

import json
import time
from contextlib import nullcontext, suppress
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from app.tasks.backup_lock import BackupLockLeaseError, backup_worker_restart_guard

from ..lib import service_ops, service_release
from ..lib.confirm_token import confirm_gate
from ..lib.neri_runner_deploy import bootstrap_runner, deploy_runner
from ..lib.usage import usage
from ..output import output_error

app = typer.Typer(
    help=(
        "Project service lifecycle through st. Use rebuild/restart instead of "
        "raw systemctl or docker commands so build, migrations, unit sync, "
        "health checks, and seed sync stay together."
    )
)


class RebuildScope(StrEnum):
    full = "full"
    backend = "backend"
    frontend = "frontend"
    worker = "worker"


@app.command("bootstrap-runner")
@usage(
    surface="st.service.runner-bootstrap",
    cmd="st service bootstrap-runner neri",
    when="perform the one-time controlled adoption of a legacy Neri local-lab runner",
    precautions=(
        "run only after inspection proves the fixed legacy two-file layout and no retained deployment interlock",
        "two-pass confirmation is required because both local-lab runner services are stopped and restarted",
        "an uncertain result retains the deployment marker; inspect its durable receipt and never retry blindly",
        "the command is restricted to the fixed Neri runner adapter, VM, services, paths, and source files",
    ),
    task_types=("vm-repair", "devops"),
    on_demand="VM repair",
    tier="reference",
)
def runner_bootstrap(
    project: Annotated[str, typer.Argument(help="Project id with the fixed Neri runner adapter")],
    confirm: Annotated[str | None, typer.Option("--confirm", help="Confirm token from preview run")] = None,
) -> None:
    """Adopt a legacy Neri runner into guarded release management."""
    services = _load(project)
    if services.runner_adapter is None:
        output_error("Project has no managed runner adapter.")
        raise typer.Exit(1)
    confirm_gate(
        f"service-runner-bootstrap-{services.project_id}",
        confirm,
        [
            f"BOOTSTRAP LEGACY RUNNER: {services.project_id}",
            "This stops and restarts both fixed local-lab runner services.",
            "The old source bundle is preserved and all activation steps are durably recorded.",
            "Any uncertain mutation retains the interlock for manual inspection.",
        ],
        f"st service bootstrap-runner {services.project_id}",
    )
    raise typer.Exit(bootstrap_runner(services.root, services.runner_adapter))


def _load(project: str) -> service_ops.ProjectServices:
    try:
        return service_ops.load_project(project)
    except service_ops.ServiceError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None


def _restore_previous_units(
    project: service_ops.ProjectServices,
    release: service_release.PreparedRelease,
) -> None:
    """Keep the next restart recoverable after candidate activation fails."""
    try:
        previous_root = service_release.previous_source_root(release)
        if previous_root is None:
            service_release.mark_phase(
                release,
                "rollback",
                status="unavailable",
                database="not_rolled_back",
            )
            return
        previous = service_ops.project_at_source(project, previous_root)
        restored = service_ops.sync_systemd_units(previous) == 0
        service_release.mark_phase(
            release,
            "rollback",
            status="units_restored" if restored else "units_restore_failed",
            previous_source_root=str(previous_root),
            database="not_rolled_back; migration downgrade is unsupported",
            running_services="not_restarted_automatically",
        )
    except (service_ops.ServiceError, service_release.ReleaseError):
        service_release.mark_phase(
            release,
            "rollback",
            status="units_restore_failed",
            database="not_rolled_back; migration downgrade is unsupported",
            running_services="requires_manual_recovery",
        )


@app.command()
def status(
    project_arg: Annotated[
        str | None,
        typer.Argument(help="Project id. Omit to show all projects."),
    ] = None,
    project_option: Annotated[
        str | None,
        typer.Option("--project", "-P", help="Project id. Alias for PROJECT."),
    ] = None,
) -> None:
    """Show managed service status through the canonical service path."""
    if project_arg and project_option and project_arg != project_option:
        output_error("Pass project either as PROJECT or --project/-P, not both.")
        raise typer.Exit(1)
    project = project_option or project_arg
    projects = [project] if project else service_ops.project_ids()
    errors = 0
    for project_id in projects:
        services = _load(project_id)
        parts = []
        for svc in services.all_services:
            state = service_ops.service_state(svc)
            parts.append(f"{svc}:{state}")
            errors += state != "active" and not (svc in services.optional_workers and state == "inactive")
        print(f"{services.project_id:<15} {' '.join(parts)}")
    raise typer.Exit(1 if errors else 0)


@app.command()
@usage(
    surface="st.service.rebuild",
    cmd="st service rebuild <project> --detach",
    when=(
        "any code/config/worker change in a managed project needs to go live; "
        "use this for the build+migrate+restart cycle, never raw pnpm/npm/uv build "
        "or systemctl restart"
    ),
    precautions=(
        "st pulse --gate first",
        "explicit project, not cwd-implicit",
        "required application workers belong in project.identity.json services.default_workers and rebuild automatically",
        "active optional workers restart with backend changes; inactive optional workers stay stopped",
        "--include-all-workers explicitly starts all optional workers",
        "use full scope for shared or uncertain changes; worker scope includes backend consumers",
        "never run raw pnpm run build / npm build / uv pip install + manual systemctl restart for a managed project",
    ),
    examples=(
        "st service rebuild summitflow",
        "st service rebuild agent-hub --detach",
        "st -P agent-hub service rebuild",
    ),
    task_types=("devops", "config", "frontend", "backend"),
    tier="mandate",
)
def rebuild(
    project: Annotated[str, typer.Argument(help="Project id to rebuild")],
    detach: Annotated[bool, typer.Option("--detach", help="Queue rebuild in background")] = False,
    include_all_workers: Annotated[
        bool,
        typer.Option("--include-all-workers", help="Restart protected optional workers too"),
    ] = False,
    scope: Annotated[
        RebuildScope,
        typer.Option("--scope", help="Explicit isolated component; use full for shared or uncertain changes. Worker includes backend consumers."),
    ] = RebuildScope.full,
    worker: Annotated[
        list[str] | None,
        typer.Option("--worker", help="Also restart this declared worker, including inactive optional workers. Repeatable."),
    ] = None,
    acceptance: Annotated[
        Path | None,
        typer.Option(
            "--acceptance",
            help="Full successful local-acceptance receipt. Omit to accept the current clean HEAD locally.",
        ),
    ] = None,
) -> None:
    """Build, migrate, restart, and health-check a project."""
    services = _load(project)
    requested_workers = tuple(worker or ())
    unknown = set(requested_workers) - set(services.workers(include_all=True))
    if unknown or (scope == RebuildScope.frontend and (requested_workers or include_all_workers)):
        output_error("Unknown worker or frontend-only scope combined with worker selection.")
        raise typer.Exit(1)
    overlapping_components = (
        services.backend_dir.is_relative_to(services.frontend_dir)
        or services.frontend_dir.is_relative_to(services.backend_dir)
    )
    if scope != RebuildScope.full and overlapping_components:
        print("[service] shared component directory; using full rebuild")
        scope = RebuildScope.full
    if detach:
        try:
            accepted_source = service_ops.resolve_accepted_source(services, acceptance)
            raise typer.Exit(
                service_ops.queue_detached(
                    project,
                    include_all_workers,
                    scope=scope.value,
                    workers=requested_workers,
                    accepted_source=accepted_source,
                )
            )
        except (service_ops.ServiceError, service_release.ReleaseError) as exc:
            output_error(str(exc))
            raise typer.Exit(1) from None
    backend = scope != RebuildScope.frontend
    frontend = scope in (RebuildScope.full, RebuildScope.frontend)
    if scope != RebuildScope.full:
        print(
            "[service] stable releases build the full accepted source; "
            f"restart scope remains {scope.value}"
        )
    # Capture intent before any lifecycle mutation. Backend and worker scopes
    # share one environment, so all running consumers must receive the update.
    active_optional = tuple(
        name for name in services.optional_workers if service_ops.service_state(name) == "active"
    ) if backend else ()
    workers = tuple(dict.fromkeys((
        *services.default_workers,
        *(services.optional_workers if include_all_workers else active_optional),
        *requested_workers,
    ))) if backend else ()
    start_time = time.time()
    errors = 0
    release: service_release.PreparedRelease | None = None
    development_services = services
    development_root = services.root
    try:
        with (
            service_release.deployment_lock(services.project_id),
            (backup_worker_restart_guard() if services.project_id == "summitflow" and backend
             else nullcontext(lambda: None)) as assert_backup_restart_owned,
        ):
            release, services = service_ops.prepare_accepted_release(services, acceptance)
            service_release.mark_phase(
                release,
                "deployment_scope",
                status="selected",
                scope=scope.value,
                release_scope="full",
                workers=list(workers),
            )
            print(
                f"Rebuilding {services.project_id} (scope: {scope.value}, "
                f"source: {release.source.source_commit}, build: {release.build_id})"
            )
            # Freeze and verify the runner before any host lifecycle mutation. Worker
            # scope also updates backend consumers, so it follows the same contract.
            if (
                backend
                and services.runner_adapter is not None
                and deploy_runner(services.root, services.runner_adapter) != 0
            ):
                service_release.fail_release(release, "runner")
                print("[service] rebuild stopped: runner deployment failed")
                raise typer.Exit(1)
            steps = [("infrastructure", lambda: service_ops.ensure_infra(services))]
            steps.append(("backend_dependencies", lambda: service_ops.sync_backend(services)))
            steps.append(("frontend_build", lambda: service_ops.build_frontend(services)))
            if backend:
                steps.append(("migrations", lambda: service_ops.run_migrations(services)))
            else:
                service_release.mark_phase(
                    release,
                    "migrations",
                    status="not_applicable",
                    reason="frontend_restart_scope",
                )
            steps.append(("systemd_units", lambda: service_ops.sync_systemd_units(services)))
            for name, step in steps:
                assert_backup_restart_owned()
                phase_started = time.monotonic()
                if step() != 0:
                    service_release.mark_phase(
                        release,
                        name,
                        status="failed",
                        duration_seconds=time.monotonic() - phase_started,
                    )
                    if name == "systemd_units":
                        _restore_previous_units(development_services, release)
                    service_release.fail_release(release, name)
                    print(
                        f"[service] rebuild stopped: {name.replace('_', ' ')} failed; "
                        "services were not restarted"
                    )
                    raise typer.Exit(1)
                service_release.mark_phase(
                    release,
                    name,
                    status="succeeded",
                    duration_seconds=time.monotonic() - phase_started,
                )
            skipped = [name for name in services.optional_workers if name not in workers]
            if skipped:
                print("[service] leaving optional workers unchanged: " + " ".join(skipped))
            restarted: list[str] = []
            restart_started = time.monotonic()
            if backend and services.backend_service:
                assert_backup_restart_owned()
                errors += service_ops.restart_service(
                    services.backend_service, port=services.backend_port
                ) != 0
                restarted.append(services.backend_service)
            for name in workers:
                assert_backup_restart_owned()
                errors += service_ops.restart_service(name) != 0
                restarted.append(name)
            if frontend and services.frontend_service:
                assert_backup_restart_owned()
                errors += service_ops.restart_service(
                    services.frontend_service, port=services.frontend_port
                ) != 0
                restarted.append(services.frontend_service)
            service_release.mark_phase(
                release,
                "restart",
                status="succeeded" if errors == 0 else "failed",
                services=restarted,
                duration_seconds=time.monotonic() - restart_started,
            )
            health_started = time.monotonic()
            health_errors = service_ops.verify_health(services)
            errors += health_errors
            service_release.mark_phase(
                release,
                "health",
                status="succeeded" if health_errors == 0 else "failed",
                duration_seconds=time.monotonic() - health_started,
            )
            for name in workers:
                state = service_ops.service_state(name)
                print(f"[service] worker {name}: {state}")
                errors += state != "active"
            if errors == 0:
                seeds_started = time.monotonic()
                seed_errors = service_ops.sync_seeds(services) != 0
                errors += seed_errors
                service_release.mark_phase(
                    release,
                    "seeds",
                    status="failed" if seed_errors else "succeeded",
                    duration_seconds=time.monotonic() - seeds_started,
                )
            if errors:
                _restore_previous_units(development_services, release)
                service_release.fail_release(
                    release,
                    "restart_health",
                    migrations=(
                        "applied; automatic database rollback is unsupported"
                        if backend
                        else "not_applicable"
                    ),
                )
                print(f"[service] rebuild completed with {errors} error(s)")
                raise typer.Exit(1)
            service_references = service_ops.release_references_for_services(
                release.release_root.parent
            )
            service_release.complete_release(
                release, service_references=service_references
            )
            result = service_release.publish_deployment_result(
                release, project_root=development_root
            )
            print(
                f"[service] deployment_receipt={result['artifact']} "
                f"deployment_id={result['deployment_id']}"
            )
            print(f"[service] rebuild complete ({int(time.time() - start_time)}s)")
    except (service_ops.ServiceError, service_release.ReleaseError, BackupLockLeaseError) as exc:
        if release is not None:
            with suppress(service_release.ReleaseError):
                service_release.fail_release(release, "deployment")
        output_error(str(exc))
        raise typer.Exit(1) from None
    raise typer.Exit(0)


@app.command()
def restart(
    project: Annotated[str, typer.Argument(help="Project id to restart/rebuild")],
    detach: Annotated[bool, typer.Option("--detach", help="Queue restart in background")] = False,
    include_all_workers: Annotated[
        bool,
        typer.Option("--include-all-workers", help="Restart protected optional workers too"),
    ] = False,
    scope: Annotated[RebuildScope, typer.Option("--scope", help="Same explicit component scope as rebuild.")] = RebuildScope.full,
    worker: Annotated[list[str] | None, typer.Option("--worker", help="Declared worker to restart; repeatable.")] = None,
    acceptance: Annotated[
        Path | None,
        typer.Option("--acceptance", help="Full successful local-acceptance receipt."),
    ] = None,
) -> None:
    """Restart a managed project through the rebuild path."""
    rebuild(
        project,
        detach=detach,
        include_all_workers=include_all_workers,
        scope=scope,
        worker=worker,
        acceptance=acceptance,
    )


def _job_result(job_id: str) -> dict:
    try:
        return service_ops.detached_result(job_id)
    except service_ops.ServiceError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None


def _job_exit_code(record: dict) -> int:
    if record["state"] in {"succeeded", "failed"}:
        return record["exit_code"]
    return 1


@app.command("result")
def job_result(job_id: Annotated[str, typer.Argument(help="Job id returned by --detach")]) -> None:
    """Read a durable detached rebuild result, including interrupted/unknown state."""
    record = _job_result(job_id)
    print(json.dumps(record))
    raise typer.Exit(_job_exit_code(record))


@app.command("wait")
def wait_for_job(
    job_id: Annotated[str, typer.Argument(help="Job id returned by --detach")],
    timeout: Annotated[float, typer.Option("--timeout", min=0, help="Maximum seconds to await completion")] = 300,
) -> None:
    """Wait for a detached rebuild and return its actual exit code."""
    deadline = time.monotonic() + timeout
    while True:
        record = _job_result(job_id)
        if record["state"] not in {"queued", "running"} or time.monotonic() >= deadline:
            print(json.dumps(record))
            raise typer.Exit(_job_exit_code(record))
        time.sleep(min(1, max(0, deadline - time.monotonic())))


@app.command("_run-job", hidden=True)
def run_job(job_id: str) -> None:
    """Internal systemd runner; terminal result survives transient-unit collection."""
    try:
        raise typer.Exit(service_ops.run_detached_job(job_id))
    except service_ops.ServiceError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None


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
