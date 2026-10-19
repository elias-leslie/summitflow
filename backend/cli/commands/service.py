"""Project service lifecycle commands."""

from __future__ import annotations

import contextlib
import json
import os
import time
from collections.abc import Callable, Mapping
from contextlib import nullcontext, suppress
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer

from app.tasks.backup_lock import (
    BackupLockLeaseError,
    backup_restart_blockers,
    backup_worker_restart_guard,
    wait_for_backup_restart_window,
)

from ..lib import service_deploy_client, service_ops, service_release
from ..lib.confirm_token import confirm_gate
from ..lib.service_ops import wait_for_summitflow_api
from ..lib.usage import usage
from ..output import output_error
from .pulse import require_pulse_gate

app = typer.Typer(
    help=(
        "Project service lifecycle through st. Use rebuild/restart instead of "
        "raw systemctl or docker commands so build, migrations, unit sync, "
        "health checks, and seed sync stay together."
    )
)


@app.command("observe")
@usage(surface="st.service.observe", cmd="st service observe <project> --task <id> --acceptance <receipt> --evidence <json>",
       when="verify an owner-managed native deployment and issue source-bound task evidence",
       precautions=("executes the registered read-only observer from fully accepted immutable source",
                    "records the actual deployed commit and explicit runtime input equivalence; does not deploy",
                    "the server issues the receipt; arbitrary observation JSON or target overrides are rejected"),
       tier="reference")
def observe(
    project: Annotated[str, typer.Argument(help="Registered native owner project")],
    task: Annotated[str, typer.Option("--task", help="Claimed task requiring production verification")],
    acceptance: Annotated[Path, typer.Option("--acceptance", help="Successful full acceptance receipt")],
    evidence: Annotated[Path, typer.Option("--evidence", help="Write a completion evidence reference to this new file")],
) -> None:
    from ..client import APIError, STClient

    try:
        with STClient(project_id=project) as client:
            receipts = client.post(client._url(f"/tasks/{task}/deployment-observations"),
                                   {"acceptance_receipt": str(acceptance.resolve(strict=True))})
        with evidence.open("x") as stream:
            json.dump({"native_deployment_receipt": receipts["deployment"]["receipt_id"]}, stream)
            stream.write("\n")
        print("NATIVE_DEPLOYMENT:" + json.dumps(receipts, separators=(",", ":")))
    except (APIError, ValueError, OSError, KeyError) as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None


class RebuildScope(StrEnum):
    full = "full"
    backend = "backend"
    frontend = "frontend"
    worker = "worker"


def _load(project: str) -> service_ops.ProjectServices:
    try:
        return service_ops.load_project(project)
    except service_ops.ServiceError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None


def _deploy_via_socket(services: service_ops.ProjectServices, user: str, verb: str, sha: str | None) -> int:
    """Hand the verb to the project's deploy gate and stream its answer."""
    try:
        return service_deploy_client.send(user, services.project_id, sha or service_deploy_client.main_sha(services.root), verb)
    except OSError as exc:
        output_error(f"deploy gate for {services.project_id} ({user}) unavailable: {exc}")
        return 1


def _restore_previous_units(
    project: service_ops.ProjectServices,
    release: service_release.PreparedRelease,
) -> bool:
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
            return False
        previous = service_ops.project_at_source(project, previous_root)
        added_monitor = (
            "summitflow-host-monitor.service" in project.default_workers
            and "summitflow-host-monitor.service" not in previous.default_workers
        )
        if added_monitor:
            service_ops.run(["systemctl", "--user", "disable", "--now", "summitflow-host-monitor.service"])
        restored = service_ops.sync_systemd_units(previous) == 0
        service_release.mark_phase(
            release,
            "rollback",
            status="units_restored" if restored else "units_restore_failed",
            previous_source_root=str(previous_root),
            database="not_rolled_back; migration downgrade is unsupported",
            running_services="not_restarted_automatically",
        )
        return restored
    except (service_ops.ServiceError, service_release.ReleaseError):
        service_release.mark_phase(
            release,
            "rollback",
            status="units_restore_failed",
            database="not_rolled_back; migration downgrade is unsupported",
            running_services="requires_manual_recovery",
        )
        return False


def _rollback_monitor_and_reader(
    candidate: service_ops.ProjectServices,
    development: service_ops.ProjectServices,
    release: service_release.PreparedRelease,
    backend_restart_attempted: bool,
) -> bool:
    """Restore the old reader before removing its candidate collector/state."""
    if not _restore_previous_units(development, release):
        print("[service] prior reader unit unavailable; retaining system collector for recovery")
        return False
    if backend_restart_attempted and service_ops.restart_service(
        candidate.backend_service, port=candidate.backend_port
    ) != 0:
        # The old reader could not resume. Keep the candidate pair recoverable.
        restored = service_ops.sync_systemd_units(candidate) == 0
        restarted = restored and service_ops.restart_service(candidate.backend_service, port=candidate.backend_port) == 0
        print(f"[service] previous reader failed; system collector retained, candidate reader restart {'succeeded' if restarted else 'requires recovery'}")
        return False
    if service_ops.host_monitor_deployment(candidate, release.build_id, "rollback") != 0:
        restored = service_ops.sync_systemd_units(candidate) == 0
        restarted = restored and service_ops.restart_service(candidate.backend_service, port=candidate.backend_port) == 0
        print(f"[service] monitor rollback failed; candidate reader restart {'succeeded' if restarted else 'failed'}, deployment receipt requires recovery")
        return False
    service_release.mark_phase(release, "host_monitor_rollback", status="succeeded",
                               reader="previous_restarted" if backend_restart_attempted else "previous_running")
    return True


def _rollback_monitor_after_unexpected_failure(
    candidate: service_ops.ProjectServices,
    development: service_ops.ProjectServices,
    release: service_release.PreparedRelease,
    backend_restart_attempted: bool,
) -> None:
    """Best-effort collector rollback when the rebuild fails outside its handled errors.

    The privileged rollback runs under /usr/bin/python3 -I, so it still works when
    the backend environment that raised the failure is damaged.
    """
    print("[service] unexpected rebuild failure after collector activation; rolling back collector")
    try:
        if _rollback_monitor_and_reader(candidate, development, release, backend_restart_attempted):
            return
        print("[service] collector retained for recovery; see messages above")
        return
    except Exception as exc:
        print(f"[service] reader restore failed ({type(exc).__name__}: {exc}); rolling back collector directly")
    try:
        rolled_back = service_ops.host_monitor_deployment(candidate, release.build_id, "rollback") == 0
    except Exception as exc:
        print(f"[service] collector rollback raised {type(exc).__name__}: {exc}")
        rolled_back = False
    if not rolled_back:
        print(
            "[service] collector rollback FAILED; recover with: sudo /usr/bin/python3 -I "
            f"{candidate.root / 'backend/cli/lib/host_monitor_deploy.py'} rollback --source {candidate.root} "
            f"--uid {os.getuid()} --gid {os.getgid()} --transaction {release.build_id}"
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
        if user := service_deploy_client.delegated_user(services.runtime_user):
            errors += _deploy_via_socket(services, user, "status", None) != 0
            continue
        parts = []
        for svc in services.all_services:
            state = service_ops.service_state(svc)
            errors += state != "active" and not (svc in services.optional_workers and state == "inactive")
            if paired := service_ops.activated_service(svc):
                # The activated service is idle between activations; only failure is an error.
                paired_state = service_ops.service_state(paired)
                errors += paired_state == "failed"
                state = f"{state}({paired}:{paired_state})"
            parts.append(f"{svc}:{state}")
        print(f"{services.project_id:<15} {' '.join(parts)}")
    raise typer.Exit(1 if errors else 0)


def _acceptance_line(source: Mapping[str, Any] | None, *, supplied: bool) -> str:
    """Say how acceptance was satisfied: a supplied receipt, a reused one, or a fresh run."""
    source = source if isinstance(source, Mapping) else {}
    how = "supplied" if supplied else "reused" if source.get("reused") else "fresh"
    lookup = source.get("reuse_lookup_ms")
    detail = f" lookup_ms={lookup:.0f}" if how == "reused" and isinstance(lookup, (int, float)) else ""
    return f"[service] acceptance={how} id={str(source.get('acceptance_id') or '?')[:12]}{detail}"


# Set by the detached job runner: a queued rebuild waits out backups instead
# of being refused after its acceptance already ran.
WAIT_FOR_BACKUPS_ENV = "ST_REBUILD_WAIT_FOR_BACKUPS"


def _backup_restart_preflight(*, detach: bool) -> None:
    """Judge the backup restart guard before acceptance spends minutes.

    Backups run in the SummitFlow worker this rebuild restarts. The guard
    itself still reserves and rechecks before any restart.
    """
    if os.environ.get(WAIT_FOR_BACKUPS_ENV) == "1":
        try:
            wait_for_backup_restart_window()
        except BackupLockLeaseError as exc:
            output_error(str(exc))
            raise typer.Exit(1) from None
        return
    try:
        blockers = backup_restart_blockers()
    except Exception:
        output_error("Cannot verify backup ownership; rebuild refused. Restore Redis access, then retry.")
        raise typer.Exit(1) from None
    if not blockers:
        return
    if detach:
        print("[service] backups active (" + ", ".join(blockers) + "); the detached job will wait for them, up to 2h")
        return
    output_error("Backups active: " + ", ".join(blockers)
                 + ". Wait for completion or explicitly cancel in Backups, then retry the rebuild (or use --detach to queue it).")
    raise typer.Exit(1)


ReleaseStep = tuple[str, Callable[[], int]]


def _selected_workers(
    services: service_ops.ProjectServices,
    *,
    backend: bool,
    include_all_workers: bool,
    requested_workers: tuple[str, ...],
) -> tuple[str, ...]:
    """Capture worker restart intent before any lifecycle mutation.

    Backend and worker scopes share one environment, so all running consumers
    must receive the update.
    """
    if not backend:
        return ()
    active_optional = tuple(
        name for name in services.optional_workers if service_ops.service_state(name) == "active"
    )
    return tuple(dict.fromkeys((
        *services.default_workers,
        *(services.optional_workers if include_all_workers else active_optional),
        *requested_workers,
    )))


def _timed_phase(release: service_release.PreparedRelease, name: str, run: Callable[[], int]) -> int:
    """Run one phase and record it as succeeded only when it returns 0."""
    started = time.monotonic()
    result = run()
    service_release.mark_phase(
        release,
        name,
        status="succeeded" if result == 0 else "failed",
        duration_seconds=time.monotonic() - started,
    )
    return result


def _release_steps(
    services: service_ops.ProjectServices,
    release: service_release.PreparedRelease,
    *,
    backend: bool,
    development_root: Path,
) -> list[ReleaseStep]:
    """List the pre-restart release steps; frontend scope records migrations as not applicable."""
    steps: list[ReleaseStep] = [("infrastructure", lambda: service_ops.ensure_infra(services))]
    steps.append(("backend_dependencies", lambda: service_ops.sync_backend(services)))
    if backend:
        steps.append(("host_monitor_build", lambda: service_ops.build_host_monitor(services)))
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
    if backend and services.release_install:
        steps.append(("release_install", lambda: service_ops.run_release_install(
            services, development_root=development_root, source_commit=release.source.source_commit)))
    if backend:
        steps.append(("host_monitor_policy", lambda: service_ops.sync_host_monitor_policy(services)))
    return steps


def _run_release_steps(
    steps: list[ReleaseStep],
    release: service_release.PreparedRelease,
    development_services: service_ops.ProjectServices,
    assert_backup_restart_owned: Callable[[], None],
) -> None:
    """Run each step in order; the first failure fails the release before any restart."""
    for name, step in steps:
        assert_backup_restart_owned()
        if _timed_phase(release, name, step) != 0:
            if name == "systemd_units":
                _restore_previous_units(development_services, release)
            service_release.fail_release(release, name)
            print(
                f"[service] rebuild stopped: {name.replace('_', ' ')} failed; "
                "services were not restarted"
            )
            raise typer.Exit(1)


def _restart_services(
    services: service_ops.ProjectServices,
    release: service_release.PreparedRelease,
    workers: tuple[str, ...],
    *,
    restart_backend: bool,
    frontend: bool,
    monitor_activated: bool,
    assert_backup_restart_owned: Callable[[], None],
) -> int:
    """Restart backend, workers, then frontend; return the restart error count.

    The caller decides ``restart_backend`` and marks the backend restart as
    attempted before calling, so its rollback handlers see it even when the
    guard or a restart raises here.
    """
    errors = 0
    restarted: list[str] = []
    restart_started = time.monotonic()
    if restart_backend and services.backend_service:
        assert_backup_restart_owned()
        errors += service_ops.restart_service(
            services.backend_service, port=services.backend_port
        ) != 0
        restarted.append(services.backend_service)
    for name in workers:
        if monitor_activated and name == "summitflow-host-monitor.service":
            restarted.append(name)
            continue
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
    return errors


def _verify_and_seed(
    services: service_ops.ProjectServices,
    release: service_release.PreparedRelease,
    workers: tuple[str, ...],
    errors: int,
) -> int:
    """Check health and worker state, sync seeds only when nothing failed; return total errors."""
    errors += _timed_phase(release, "health", lambda: service_ops.verify_health(services))
    for name in workers:
        state = service_ops.service_state(name)
        print(f"[service] worker {name}: {state}")
        errors += state != "active"
    if errors == 0:
        errors += _timed_phase(release, "seeds", lambda: service_ops.sync_seeds(services)) != 0
    return errors


@app.command()
@usage(
    surface="st.service.rebuild",
    cmd="st service rebuild <project> --detach",
    when=(
        "deployed code/config/worker behavior changed (managed build+migrate+restart); "
        "never raw pnpm/npm/uv build or systemctl restart"
    ),
    precautions=(
        "explicit project, not cwd; resolve blockers its preflight reports",
        "no ask needed: deploys committed HEAD only; preflight refuses when unsafe",
        "full scope for shared or uncertain changes; worker scope includes backend consumers",
        "required and active optional workers restart automatically; --include-all-workers also starts inactive optional workers",
    ),
    examples=(
        "st service rebuild summitflow",
        "st service rebuild agent-hub --detach",
        "st -P agent-hub service rebuild agent-hub",
    ),
    task_types=("devops", "config", "frontend", "backend"),
    tier="mandate",
)
def rebuild(
    project: Annotated[str, typer.Argument(help="Project id to rebuild")],
    detach: Annotated[bool, typer.Option("--detach", help="Queue rebuild in background")] = False,
    include_all_workers: Annotated[
        bool,
        typer.Option("--include-all-workers", help="Start or restart all declared optional workers, including inactive ones"),
    ] = False,
    scope: Annotated[
        RebuildScope,
        typer.Option("--scope", help="Restart/migration scope; release build uses full accepted source. Worker includes backend consumers; use full for shared changes."),
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
    migrate_monitor_store: Annotated[
        bool,
        typer.Option("--migrate-monitor-store", help="Explicitly convert the stopped monitor database to 512-byte pages after the reader lock release is live"),
    ] = False,
    with_ack: Annotated[
        str | None,
        typer.Option("--with-ack", help="Request id the repo's holder acked yes"),
    ] = None,
    rollback: Annotated[
        bool,
        typer.Option("--rollback", help="Deploy an accepted commit that does not contain the live release"),
    ] = False,
    source_repo: Annotated[
        Path | None,
        typer.Option("--source-repo", help="Bare mirror to read git state from instead of the checkout (used by the deploy gate); needs --sha"),
    ] = None,
    sha: Annotated[
        str | None,
        typer.Option("--sha", help="Full commit id to deploy: with --source-repo it is read from the mirror; for a runtime_user project it replaces the checkout's main"),
    ] = None,
) -> None:
    """Build, migrate, restart, and health-check a project."""
    services = _load(project)
    from ..lib import coord

    if source_repo is not None:
        if detach:
            output_error("--source-repo cannot be combined with --detach.")
            raise typer.Exit(1)
        try:
            services = service_ops.use_source_repo(services, source_repo, sha or "")
        except service_ops.ServiceError as exc:
            output_error(str(exc))
            raise typer.Exit(1) from None
        print("[service] installing the pinned source's tools for acceptance")
        if service_ops.install_clone_dependencies(services) != 0:
            output_error("Could not install dependencies in the pinned source.")
            raise typer.Exit(1)
    elif user := service_deploy_client.delegated_user(services.runtime_user):
        if acceptance or with_ack or migrate_monitor_store:
            output_error("--acceptance, --with-ack and --migrate-monitor-store are not available through the deploy gate.")
            raise typer.Exit(1)
        raise typer.Exit(_deploy_via_socket(services, user, "rollback" if rollback else "deploy", sha))
    elif sha:
        output_error("--sha needs --source-repo or a project with a runtime user.")
        raise typer.Exit(1)
    try:
        if source_repo is None:  # a pinned mirror has no working tree for other agents to hold
            coord.guard(services.root, "rebuild", with_ack=with_ack)
    except coord.CoordBlocked as exc:
        output_error(str(exc))
        raise typer.Exit(2) from None
    if migrate_monitor_store and (project != "summitflow" or scope == RebuildScope.frontend):
        output_error("--migrate-monitor-store requires a SummitFlow backend or full rebuild.")
        raise typer.Exit(1)
    requested_workers = tuple(worker or ())
    unknown = set(requested_workers) - set(services.workers(include_all=True))
    if unknown or (scope == RebuildScope.frontend and (requested_workers or include_all_workers)):
        output_error("Unknown worker or frontend-only scope combined with worker selection.")
        raise typer.Exit(1)
    wait_for_summitflow_api()
    require_pulse_gate(services.project_id)
    overlapping_components = (
        services.backend_dir.is_relative_to(services.frontend_dir)
        or services.frontend_dir.is_relative_to(services.backend_dir)
    )
    if scope != RebuildScope.full and overlapping_components:
        print("[service] shared component directory; using full rebuild")
        scope = RebuildScope.full
    if scope != RebuildScope.frontend and service_ops.preflight_host_monitor(services) != 0:
        raise typer.Exit(1)
    if services.project_id == "summitflow" and scope != RebuildScope.frontend:
        _backup_restart_preflight(detach=detach)
    if detach:
        try:
            with coord.acked(with_ack):
                accepted_source = service_ops.resolve_accepted_source(services, acceptance, rollback=rollback)
            print(_acceptance_line(accepted_source, supplied=acceptance is not None))
            raise typer.Exit(
                service_ops.queue_detached(
                    project,
                    include_all_workers,
                    scope=scope.value,
                    workers=requested_workers,
                    accepted_source=accepted_source,
                    with_ack=with_ack,
                    rollback=rollback,
                    **({"migrate_monitor_store": True} if migrate_monitor_store else {}),
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
    workers = _selected_workers(
        services, backend=backend, include_all_workers=include_all_workers, requested_workers=requested_workers
    )
    start_time = time.time()
    release: service_release.PreparedRelease | None = None
    monitor_activated = False
    backend_restart_attempted = False
    development_services = services
    development_root = services.git_root
    try:
        with (
            service_release.deployment_lock(services.project_id),
            (backup_worker_restart_guard() if services.project_id == "summitflow" and backend
             else nullcontext(lambda: None)) as assert_backup_restart_owned,
        ):
            with coord.acked(with_ack):
                release, services = service_ops.prepare_accepted_release(services, acceptance, rollback=rollback)
            print(_acceptance_line(vars(release.source), supplied=acceptance is not None))
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
            _run_release_steps(
                _release_steps(services, release, backend=backend, development_root=development_root),
                release,
                development_services,
                assert_backup_restart_owned,
            )
            if migrate_monitor_store:
                assert_backup_restart_owned()
                try:
                    migration = service_ops.migrate_host_monitor_store(services)
                except service_ops.ServiceError:
                    service_release.mark_phase(release, "host_monitor_store_migration", status="failed")
                    _restore_previous_units(development_services, release)
                    service_release.fail_release(release, "host_monitor_store_migration")
                    raise
                service_release.mark_phase(
                    release,
                    "host_monitor_store_migration",
                    status=migration.status,
                    receipt=str(migration.receipt) if migration.receipt else None,
                )
            if backend and service_ops.has_host_monitor(services):
                if service_ops.host_monitor_deployment(services, release.build_id, "install") != 0:
                    _restore_previous_units(development_services, release)
                    service_release.fail_release(release, "host_monitor_install")
                    raise typer.Exit(1)
                monitor_activated = True
                service_release.mark_phase(release, "host_monitor_install", status="succeeded")
                if service_ops.verify_host_monitor(services) != 0:
                    raise service_ops.ServiceError("root collector activation failed verification")
            skipped = [name for name in services.optional_workers if name not in workers]
            if skipped:
                print("[service] leaving optional workers unchanged: " + " ".join(skipped))
            restart_backend = bool(backend and services.backend_service)
            if restart_backend:
                backend_restart_attempted = True
            errors = _restart_services(
                services,
                release,
                workers,
                restart_backend=restart_backend,
                frontend=frontend,
                monitor_activated=monitor_activated,
                assert_backup_restart_owned=assert_backup_restart_owned,
            )
            errors = _verify_and_seed(services, release, workers, errors)
            if errors:
                if monitor_activated:
                    _rollback_monitor_and_reader(services, development_services, release, backend_restart_attempted)
                    monitor_activated = False
                else:
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
            if monitor_activated:
                if service_ops.verify_host_monitor(services) != 0:
                    raise service_ops.ServiceError("collector owner access failed after backend restart")
                if service_ops.host_monitor_deployment(services, release.build_id, "finalize") != 0:
                    raise service_ops.ServiceError("collector deployment receipt could not be finalized")
                monitor_activated = False
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
            if service_ops.install_st_monitor_launcher(development_services) != 0:
                print("[service] release is live; st monitor launcher needs installation")
                raise typer.Exit(1)
            print(f"[service] rebuild complete ({int(time.time() - start_time)}s)")
    except (service_ops.ServiceError, service_release.ReleaseError, BackupLockLeaseError) as exc:
        if monitor_activated and release is not None:
            _rollback_monitor_and_reader(services, development_services, release, backend_restart_attempted)
        if release is not None:
            with suppress(service_release.ReleaseError):
                service_release.fail_release(release, "deployment")
        output_error(str(exc))
        raise typer.Exit(1) from None
    except BaseException as exc:
        # Any other failure (e.g. a dependency vanishing mid-deploy) must not
        # strand an activated collector and its .pending receipt marker.
        if monitor_activated and release is not None:
            _rollback_monitor_after_unexpected_failure(
                services, development_services, release, backend_restart_attempted
            )
        if release is not None and not isinstance(exc, typer.Exit):
            with suppress(Exception):
                service_release.fail_release(release, "deployment")
        raise
    raise typer.Exit(0)


@app.command()
def restart(
    project: Annotated[str, typer.Argument(help="Project id to restart/rebuild")],
    detach: Annotated[bool, typer.Option("--detach", help="Queue restart in background")] = False,
    include_all_workers: Annotated[
        bool,
        typer.Option("--include-all-workers", help="Start or restart all declared optional workers, including inactive ones"),
    ] = False,
    scope: Annotated[RebuildScope, typer.Option("--scope", help="Same explicit component scope as rebuild.")] = RebuildScope.full,
    worker: Annotated[list[str] | None, typer.Option("--worker", help="Declared worker to restart; repeatable.")] = None,
    acceptance: Annotated[
        Path | None,
        typer.Option("--acceptance", help="Full successful local-acceptance receipt."),
    ] = None,
    with_ack: Annotated[
        str | None,
        typer.Option("--with-ack", help="Request id the repo's holder acked yes"),
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
        with_ack=with_ack,
    )


def _job_result(job_id: str) -> dict:
    try:
        return service_ops.detached_result(job_id)
    except service_ops.ServiceError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None


def _compact_job(record: dict) -> dict:
    """Keep the job record readable: the embedded acceptance receipt stays on disk."""
    compact = dict(record)
    source = compact.get("source")
    if isinstance(source, dict) and "checks" in source:
        compact["source"] = {key: value for key, value in source.items() if key != "checks"}
    log_path = record.get("log_path")
    if record.get("state") == "failed" and log_path:
        with contextlib.suppress(OSError):
            compact["log_tail"] = Path(log_path).read_text(errors="replace").splitlines()[-8:]
    return compact


def _job_exit_code(record: dict) -> int:
    if record["state"] in {"succeeded", "failed"}:
        return record["exit_code"]
    return 1


@app.command("result")
def job_result(job_id: Annotated[str, typer.Argument(help="Job id returned by --detach")]) -> None:
    """Read a durable detached rebuild result, including interrupted/unknown state."""
    record = _job_result(job_id)
    print(json.dumps(_compact_job(record)))
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
            print(json.dumps(_compact_job(record)))
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


@app.command("stop-unit")
def stop_unit(
    project: Annotated[str, typer.Argument(help="Project id that created the unit")],
    unit: Annotated[str, typer.Argument(help="Transient <project>-*.service or .scope unit")],
) -> None:
    """Stop one transient user unit a project created (e.g. a leftover smoke-test unit).

    Refuses persistent units, managed services and names outside the project prefix.
    """
    code, state = service_ops.stop_transient_unit(_load(project), unit)
    typer.echo(f"STOP-UNIT:{project}|unit={unit}|state={state}")
    raise typer.Exit(code)


@app.command()
def stop(
    project: Annotated[str, typer.Argument(help="Project id to stop")] = "summitflow",
    confirm: Annotated[str | None, typer.Option("--confirm", help="Confirm token from preview run")] = None,
) -> None:
    """Stop a managed project's service set. Two-pass confirmation required."""
    services = _load(project)
    if user := service_deploy_client.delegated_user(services.runtime_user):
        raise typer.Exit(_deploy_via_socket(services, user, "stop", None))
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
