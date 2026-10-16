"""Regression coverage for managed lifecycle selection and failure reporting."""

import subprocess
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from cli.commands import service
from cli.lib import service_ops, service_release


def test_service_admission_is_only_for_explicit_build_dependency_phases(monkeypatch, tmp_path):
    admitted: list[str] = []
    worker = Mock()
    worker.run.return_value = subprocess.CompletedProcess([], 0, "", "")
    ordinary = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))

    @contextmanager
    def admission(label):
        admitted.append(label)
        yield worker

    monkeypatch.setattr(service_ops, "heavy_work", admission)
    monkeypatch.setattr(service_ops.subprocess, "run", ordinary)
    assert service_ops.run(["systemctl", "--user", "status"], cwd=tmp_path, quiet_success=True) == 0
    assert admitted == []
    ordinary.assert_called_once()
    assert service_ops.run(["uv", "sync", "--locked"], cwd=tmp_path,
                           env={"FIXTURE": "kept"}, quiet_success=True, _heavy=True) == 0
    assert admitted == ["managed service build/dependencies"]
    worker.run.assert_called_once()
    assert worker.run.call_args.args == (["uv", "sync", "--locked"],)
    assert worker.run.call_args.kwargs["cwd"] == tmp_path
    assert worker.run.call_args.kwargs["env"]["FIXTURE"] == "kept"
    ordinary.assert_called_once()


@pytest.fixture
def project(tmp_path: Path) -> service_ops.ProjectServices:
    return service_ops.ProjectServices(
        project_id="example", root=tmp_path, backend_service="backend.service",
        frontend_service="frontend.service", default_workers=("required.service",),
        optional_workers=("active.service", "stopped.service"), backend_port=8001,
        frontend_port=3001, backend_dir=tmp_path / "backend", frontend_dir=tmp_path / "frontend",
        health_endpoint="/health",
    )


@pytest.fixture
def lifecycle(monkeypatch, project):
    monkeypatch.setattr(service, "_load", lambda _: project)
    monkeypatch.setattr(service, "backup_restart_blockers", lambda: [])
    monkeypatch.delenv(service.WAIT_FOR_BACKUPS_ENV, raising=False)
    calls = {}
    for name in ("ensure_infra", "sync_backend", "build_frontend", "run_migrations",
                 "sync_systemd_units", "restart_service", "verify_health", "sync_seeds"):
        calls[name] = Mock(return_value=0)
        monkeypatch.setattr(service_ops, name, calls[name])
    monkeypatch.setattr(service_ops, "service_state", lambda name: "inactive" if name == "stopped.service" else "active")
    release = service_release.PreparedRelease(
        project_id=project.project_id,
        build_id="b" * 32,
        source=service_release.AcceptedSource(
            acceptance_id="acceptance-test",
            source_commit="c" * 40,
            source_tree="d" * 40,
            acceptance_artifact="/tmp/acceptance-test.json",
        ),
        release_root=project.root / "release",
        source_root=project.root,
        receipt_path=project.root / "deployment.json",
    )
    monkeypatch.setattr(
        service_ops, "prepare_accepted_release", lambda current, _receipt=None, **_kwargs: (release, current)
    )
    monkeypatch.setattr(service_release, "deployment_lock", lambda _project: nullcontext())
    monkeypatch.setattr(service_release, "mark_phase", Mock())
    monkeypatch.setattr(service_release, "fail_release", Mock())
    monkeypatch.setattr(service_release, "complete_release", Mock())
    monkeypatch.setattr(service_ops, "release_references_for_services", Mock(return_value=set()))
    monkeypatch.setattr(
        service_release,
        "publish_deployment_result",
        lambda *_args, **_kwargs: {
            "artifact": str(release.receipt_path),
            "deployment_id": "e" * 64,
        },
    )
    return calls


def test_optional_inactive_status_is_healthy(lifecycle):
    result = CliRunner().invoke(service.app, ["status", "example"])
    assert result.exit_code == 0, result.output
    assert "stopped.service:inactive" in result.output


def test_optional_failed_status_is_not_healthy(lifecycle, monkeypatch):
    monkeypatch.setattr(service_ops, "service_state", lambda _: "failed")
    assert CliRunner().invoke(service.app, ["status", "example"]).exit_code == 1


def test_full_rebuild_preserves_optional_worker_intent(lifecycle):
    result = CliRunner().invoke(service.app, ["rebuild", "example"])
    assert result.exit_code == 0, result.output
    restarted = [call.args[0] for call in lifecycle["restart_service"].call_args_list]
    assert restarted == ["backend.service", "required.service", "active.service", "frontend.service"]


def test_rebuild_runs_preflight_once_before_lifecycle_work(lifecycle, unit_service_preflight):
    result = CliRunner().invoke(service.app, ["rebuild", "example"])
    assert result.exit_code == 0, result.output
    unit_service_preflight.assert_called_once_with("example")


def test_rebuild_preflight_block_preserves_source_and_services(lifecycle, unit_service_preflight, monkeypatch):
    import typer

    unit_service_preflight.side_effect = typer.Exit(2)
    acceptance = Mock()
    monkeypatch.setattr(service_ops, "prepare_accepted_release", acceptance)
    result = CliRunner().invoke(service.app, ["rebuild", "example"])

    assert result.exit_code == 2
    acceptance.assert_not_called()
    assert all(not operation.called for operation in lifecycle.values())


@pytest.mark.parametrize("scope", ["full", "backend", "worker"])
def test_summitflow_rebuild_refuses_busy_backup_before_mutation(lifecycle, project, monkeypatch, scope):
    from app.tasks.backup_lock import BackupLockLeaseError

    monkeypatch.setattr(service, "_load", lambda _: replace(project, project_id="summitflow"))
    guard = Mock(side_effect=BackupLockLeaseError("Backups active: AfterTimes; wait or cancel in Backups, then retry"))
    monkeypatch.setattr(service, "backup_worker_restart_guard", guard, raising=False)
    result = CliRunner().invoke(service.app, ["rebuild", "summitflow", "--scope", scope])
    assert result.exit_code == 1
    assert "Backups active" in result.output
    lifecycle["ensure_infra"].assert_not_called()
    lifecycle["restart_service"].assert_not_called()


@pytest.mark.parametrize("mode", ["foreground", "detached_job"])
def test_busy_backup_is_judged_before_acceptance(lifecycle, project, monkeypatch, mode):
    monkeypatch.setattr(service, "_load", lambda _: replace(project, project_id="summitflow"))
    blockers = [["AfterTimes (restic, mutating)"], ["AfterTimes (restic, mutating)"], []]
    monkeypatch.setattr(service, "backup_restart_blockers", lambda: blockers.pop(0) if len(blockers) > 1 else blockers[0])
    accepted = Mock(side_effect=service_ops.prepare_accepted_release)
    monkeypatch.setattr(service_ops, "prepare_accepted_release", accepted)
    # The restart-time reservation needs Redis; this test covers the earlier judgement.
    monkeypatch.setattr(service, "backup_worker_restart_guard", lambda: nullcontext(lambda: None))
    if mode == "detached_job":
        from app.tasks import backup_lock

        monkeypatch.setenv(service.WAIT_FOR_BACKUPS_ENV, "1")
        monkeypatch.setattr(backup_lock, "backup_restart_blockers", service.backup_restart_blockers)
        monkeypatch.setattr(backup_lock, "_BACKUP_RESTART_POLL_SECONDS", 0.0)
    result = CliRunner().invoke(service.app, ["rebuild", "summitflow"])
    if mode == "foreground":
        assert result.exit_code == 1
        accepted.assert_not_called()
    else:
        assert result.exit_code == 0, result.output
        accepted.assert_called_once()
        assert not blockers[0]


def test_backup_wait_is_bounded():
    from app.tasks import backup_lock
    from app.tasks.backup_lock import BackupLockLeaseError

    now = [0.0]
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(backup_lock, "backup_restart_blockers", lambda: ["AfterTimes"])
        with pytest.raises(BackupLockLeaseError):
            backup_lock.wait_for_backup_restart_window(
                timeout_seconds=90, progress=lambda _line: None,
                sleep=lambda seconds: now.__setitem__(0, now[0] + seconds), clock=lambda: now[0])
    assert now[0] >= 90


@pytest.mark.parametrize("scope", ["full", "frontend"])
def test_restart_barrier_lifetime_and_frontend_exemption(lifecycle, project, monkeypatch, scope):
    monkeypatch.setattr(service, "_load", lambda _: replace(project, project_id="summitflow"))
    events = []
    owned = Mock()

    @contextmanager
    def guard():
        events.append("held")
        try:
            yield owned
        finally:
            events.append("released")

    monkeypatch.setattr(service, "backup_worker_restart_guard", guard, raising=False)

    def restart(*_args, **_kwargs):
        assert events == (["held"] if scope == "full" else [])
        return 0

    lifecycle["restart_service"].side_effect = restart
    result = CliRunner().invoke(service.app, ["rebuild", "summitflow", "--scope", scope])
    assert result.exit_code == 0, result.output
    assert events == (["held", "released"] if scope == "full" else [])
    assert owned.called is (scope == "full")


def test_guard_loss_before_restart_refuses_stop_and_releases_barrier(lifecycle, project, monkeypatch):
    from app.tasks.backup_lock import BackupLockLeaseError

    monkeypatch.setattr(service, "_load", lambda _: replace(project, project_id="summitflow"))
    released = Mock()

    def assert_owned():
        if lifecycle["sync_systemd_units"].called:
            raise BackupLockLeaseError("Backup restart ownership unavailable")

    @contextmanager
    def guard():
        try:
            yield assert_owned
        finally:
            released()

    monkeypatch.setattr(service, "backup_worker_restart_guard", guard)
    result = CliRunner().invoke(service.app, ["rebuild", "summitflow"])
    assert result.exit_code == 1
    assert "ownership unavailable" in result.output
    lifecycle["restart_service"].assert_not_called()
    released.assert_called_once()


@pytest.mark.parametrize("scope,expected", [
    ("frontend", ["frontend.service"]),
    ("backend", ["backend.service", "required.service", "active.service"]),
    ("worker", ["backend.service", "required.service", "active.service"]),
])
def test_explicit_scope_restarts_shared_backend_consumers(lifecycle, scope, expected):
    result = CliRunner().invoke(service.app, ["rebuild", "example", "--scope", scope])
    assert result.exit_code == 0, result.output
    assert [call.args[0] for call in lifecycle["restart_service"].call_args_list] == expected
    lifecycle["sync_backend"].assert_called_once()
    lifecycle["build_frontend"].assert_called_once()
    assert lifecycle["run_migrations"].call_count == int(scope != "frontend")
    assert "stable releases build the full accepted source" in result.output


def test_named_optional_worker_is_explicit_start(lifecycle):
    result = CliRunner().invoke(service.app, ["rebuild", "example", "--scope", "worker", "--worker", "stopped.service"])
    assert result.exit_code == 1  # The fake service stays inactive after restart.
    assert "stopped.service" in [call.args[0] for call in lifecycle["restart_service"].call_args_list]


def test_unknown_worker_rejected_before_mutation(lifecycle):
    result = CliRunner().invoke(service.app, ["rebuild", "example", "--worker", "foreign.service"])
    assert result.exit_code != 0
    lifecycle["ensure_infra"].assert_not_called()


@pytest.mark.parametrize("step", ["sync_systemd_units", "sync_seeds"])
def test_lifecycle_failure_cannot_claim_completion(lifecycle, step):
    lifecycle[step].return_value = 1
    result = CliRunner().invoke(service.app, ["rebuild", "example"])
    assert result.exit_code == 1, result.output
    assert "rebuild complete (" not in result.output
    if step == "sync_systemd_units":
        lifecycle["restart_service"].assert_not_called()


def test_failed_health_restores_previous_release_units(
    lifecycle, project, monkeypatch, tmp_path
):
    previous = tmp_path / "previous" / "source"
    monkeypatch.setattr(service_release, "previous_source_root", lambda _release: previous)
    lifecycle["verify_health"].return_value = 1

    result = CliRunner().invoke(service.app, ["rebuild", "example"])

    assert result.exit_code == 1, result.output
    assert lifecycle["sync_systemd_units"].call_count == 2
    restored = lifecycle["sync_systemd_units"].call_args_list[-1].args[0]
    assert restored.root == previous
    assert restored.backend_dir == previous / "backend"


def test_frontend_frozen_install_runs_at_workspace_root_and_keeps_cache(project, monkeypatch):
    project.frontend_dir.mkdir()
    (project.frontend_dir / "package.json").write_text("{}")
    (project.root / "pnpm-workspace.yaml").write_text("packages: [frontend]\n")
    (project.root / "pnpm-lock.yaml").touch()
    (project.frontend_dir / "node_modules").mkdir()
    cache = project.frontend_dir / ".next" / "cache"
    cache.mkdir(parents=True)
    (cache / "retained").touch()
    run = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "run", run)
    assert service_ops.build_frontend(project) == 0
    assert run.call_args_list[0].args[0] == ["pnpm", "install", "--frozen-lockfile"]
    assert run.call_args_list[0].kwargs["cwd"] == project.root
    assert run.call_args_list[-1].args[0] == ["pnpm", "build"]
    assert all(call.kwargs["_heavy"] is True for call in run.call_args_list)
    assert (cache / "retained").exists()


def test_infrastructure_uses_accepted_compose_and_existing_host_secret_source(
    project, monkeypatch, tmp_path
):
    accepted_root = tmp_path / "release" / "source"
    host_root = tmp_path / "host-checkout"
    accepted_compose = accepted_root / "docker" / "compose" / "docker-compose.yml"
    host_env = host_root / "docker" / "compose" / ".env"
    accepted_compose.parent.mkdir(parents=True)
    host_env.parent.mkdir(parents=True)
    accepted_compose.write_text("services: {}\n")
    host_env.write_text("POSTGRES_PASSWORD=test-only\n")
    deployed = replace(
        project,
        root=accepted_root,
        backend_dir=accepted_root / "backend",
        frontend_dir=accepted_root / "frontend",
        host_config_root=host_root,
    )

    def capture(command, **_kwargs):
        if command[:2] == ["docker", "ps"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, "ready", "")

    run = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "capture", capture)
    monkeypatch.setattr(service_ops, "run", run)
    monkeypatch.setattr(service_ops.httpx, "get", lambda *_args, **_kwargs: SimpleNamespace(status_code=200))

    assert service_ops.ensure_infra(deployed) == 0
    command = run.call_args.args[0]
    assert command[command.index("--env-file") + 1] == str(host_env)
    assert command[command.index("-f") + 1] == str(accepted_compose)


def test_infrastructure_fails_safely_when_host_secret_source_is_missing(
    project, monkeypatch, tmp_path, capsys
):
    accepted_root = tmp_path / "release" / "source"
    compose_file = accepted_root / "docker" / "compose" / "docker-compose.yml"
    compose_file.parent.mkdir(parents=True)
    compose_file.write_text("services: {}\n")
    deployed = replace(
        project,
        root=accepted_root,
        host_config_root=tmp_path / "missing-host",
    )
    monkeypatch.setattr(
        service_ops,
        "capture",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )
    run = Mock()
    monkeypatch.setattr(service_ops, "run", run)

    assert service_ops.ensure_infra(deployed) == 1
    assert "host compose environment is unavailable" in capsys.readouterr().out
    run.assert_not_called()


def test_release_reference_discovery_includes_inactive_service_units(
    monkeypatch, tmp_path
):
    releases = tmp_path / "projects" / "summitflow" / "releases"
    active = releases / ("a" * 32)
    inactive = releases / ("b" * 32)
    system = releases / ("c" * 32)
    active.mkdir(parents=True)
    inactive.mkdir()
    system.mkdir()

    def systemctl(*args):
        if args[0] == "list-unit-files":
            return subprocess.CompletedProcess(
                args, 0, "active.service enabled\ninactive.service disabled\n", ""
            )
        if args[0] == "list-units":
            return subprocess.CompletedProcess(
                args,
                0,
                "active.service loaded active running\n"
                "stale.service not-found failed failed\n",
                "",
            )
        return subprocess.CompletedProcess(
            args,
            0,
            (
                f"Id=active.service\nLoadState=loaded\n"
                f"WorkingDirectory={active}/source/backend\n\n"
                f"Id=inactive.service\nLoadState=loaded\n"
                f"WorkingDirectory={inactive}/source/backend\n\n"
                "Id=stale.service\nLoadState=not-found\nWorkingDirectory=\n"
            ),
            "",
        )

    monkeypatch.setattr(service_ops, "systemctl", systemctl)
    monkeypatch.setattr(
        service_ops,
        "system_systemctl",
        lambda *args: (
            subprocess.CompletedProcess(args, 0, "system.service enabled\n", "")
            if args[0] == "list-unit-files"
            else subprocess.CompletedProcess(args, 0, "", "")
            if args[0] == "list-units"
            else subprocess.CompletedProcess(
                args,
                0,
                f"Id=system.service\nLoadState=loaded\nWorkingDirectory={system}/source\n",
                "",
            )
        ),
    )

    assert service_ops.release_references_for_services(releases) == {
        active,
        inactive,
        system,
    }


def test_release_reference_discovery_fails_closed_on_unknown_unit(monkeypatch, tmp_path):
    releases = tmp_path / "releases"

    def systemctl(*args):
        if args[0].startswith("list-"):
            return subprocess.CompletedProcess(args, 0, "unknown.service disabled\n", "")
        return subprocess.CompletedProcess(args, 1, "", "unavailable")

    monkeypatch.setattr(service_ops, "systemctl", systemctl)
    monkeypatch.setattr(service_ops, "system_systemctl", systemctl)

    assert service_ops.release_references_for_services(releases) is None


def test_failed_frontend_install_does_not_build(project, monkeypatch):
    project.frontend_dir.mkdir()
    (project.frontend_dir / "package.json").write_text("{}")
    (project.frontend_dir / "node_modules").mkdir()
    run = Mock(return_value=1)
    monkeypatch.setattr(service_ops, "run", run)
    assert service_ops.build_frontend(project) == 1
    assert run.call_count == 1
    assert run.call_args.args[0] == ["pnpm", "install", "--frozen-lockfile"]


def test_configured_migrations_require_alembic(project):
    project.backend_dir.mkdir()
    (project.backend_dir / "alembic.ini").touch()
    assert service_ops.run_migrations(project) == 1


@pytest.mark.parametrize("project_id, wanted, other, files", [
    # Host .env.local beats host .env, the accepted source's .env and the shell.
    ("portfolio-ai", "PORTFOLIO_DB_URL", "JOBINATOR_DB_URL", {
        "source/.env": "PORTFOLIO_DB_URL=postgresql://source-stale\n",
        "host/.env": "PORTFOLIO_DB_URL=postgresql://host-base\n",
        "host/.env.local": "PORTFOLIO_DB_URL=postgresql://approved\n"}),
    ("neri", "NERI_DB_URL", "PORTFOLIO_DB_URL", {"home/.env.local": "NERI_DB_URL=postgresql://approved\n"}),
    ("learn-o-tron", "LEARN_DB_URL", "NERI_DB_URL", {"host/backend/.env": "LEARN_DB_URL=postgresql://approved\n"}),
    ("jobinator-4000", "JOBINATOR_DB_URL", "NERI_DB_URL", {"home/.env.local": "JOBINATOR_DB_URL=postgresql://approved\n"}),
])
def test_migrations_get_only_the_approved_project_database_env(project, monkeypatch, tmp_path, project_id, wanted,
                                                              other, files):
    accepted_root = tmp_path / "source"
    backend_dir = accepted_root / "backend"
    (backend_dir / ".venv" / "bin").mkdir(parents=True)
    (backend_dir / "alembic.ini").touch()
    (backend_dir / ".venv" / "bin" / "alembic").touch()
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        extra = f"{other}=postgresql://other-project\nINTERNAL_SERVICE_SECRET=not-for-migrations\n"
        path.write_text(content + ("" if "stale" in content or "base" in content else extra))
    (tmp_path / "home").mkdir(exist_ok=True)
    monkeypatch.setattr(service_ops.Path, "home", lambda: tmp_path / "home")
    if project_id == "portfolio-ai":
        monkeypatch.setenv(wanted, "postgresql://stale-shell")
        monkeypatch.setenv("DATABASE_URL", "postgresql://other-project")
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET", raising=False)
    run = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "run", run)
    deployed = replace(project, project_id=project_id, root=accepted_root, backend_dir=backend_dir,
                       frontend_dir=accepted_root / "frontend", host_config_root=tmp_path / "host")

    assert service_ops.run_migrations(deployed) == 0
    migration_env = run.call_args.kwargs["env"]
    assert migration_env[wanted] == "postgresql://approved"
    assert not {other, "DATABASE_URL", "INTERNAL_SERVICE_SECRET"} & migration_env.keys()
    assert run.call_args.kwargs["cwd"] == backend_dir


def test_portfolio_migrations_get_their_secret_key_from_host_env(project, monkeypatch, tmp_path):
    backend_dir = tmp_path / "source" / "backend"
    (backend_dir / ".venv" / "bin").mkdir(parents=True)
    (backend_dir / "alembic.ini").touch()
    (backend_dir / ".venv" / "bin" / "alembic").touch()
    (tmp_path / "host").mkdir()
    (tmp_path / "host" / ".env.local").write_text("PORTFOLIO_SECRET_KEY=approved-key\n")
    monkeypatch.setenv("PORTFOLIO_SECRET_KEY", "stale-shell-key")
    run = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "run", run)

    for project_id, expected in (("portfolio-ai", "approved-key"), ("neri", None)):
        deployed = replace(project, project_id=project_id, root=tmp_path / "source", backend_dir=backend_dir,
                           frontend_dir=tmp_path / "source" / "frontend", host_config_root=tmp_path / "host")
        assert service_ops.run_migrations(deployed) == 0
        assert run.call_args.kwargs["env"].get("PORTFOLIO_SECRET_KEY") == expected


def test_seed_export_failure_propagates(project, monkeypatch):
    (project.backend_dir / "scripts").mkdir(parents=True)
    (project.backend_dir / "scripts" / "export_seeds.py").touch()
    (project.backend_dir / ".venv" / "bin").mkdir(parents=True)
    (project.backend_dir / ".venv" / "bin" / "python").touch()
    monkeypatch.setattr(service_ops, "run", lambda *args, **kwargs: 1)
    assert service_ops.sync_seeds(project) == 1


def test_shared_component_directory_falls_back_to_full(project, lifecycle, monkeypatch):
    monkeypatch.setattr(service, "_load", lambda _: replace(project, frontend_dir=project.backend_dir))
    result = CliRunner().invoke(service.app, ["rebuild", "example", "--scope", "backend"])
    assert result.exit_code == 0, result.output
    lifecycle["build_frontend"].assert_called_once()


def test_daemon_reload_failure_propagates(project, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    templates = project.root / "scripts" / "systemd"
    templates.mkdir(parents=True)
    (templates / "backend.service").write_text("[Service]\nExecStart=__PROJECT_ROOT__/backend/run\n")
    monkeypatch.setattr(service_ops, "run", lambda *args, **kwargs: 1)
    assert service_ops.sync_systemd_units(project) == 1


def test_start_uses_last_verified_release_instead_of_development_checkout(
    project, monkeypatch, tmp_path
):
    stable = tmp_path / "managed-release" / "source"
    synced = Mock(return_value=0)
    monkeypatch.setattr(service_release, "current_source_root", lambda _project: stable)
    monkeypatch.setattr(service_ops, "sync_systemd_units", synced)
    monkeypatch.setattr(service_ops, "service_exists", lambda _service: False)

    assert service_ops.start_services(project) == 0

    deployed = synced.call_args.args[0]
    assert deployed.root == stable
    assert deployed.backend_dir == stable / "backend"
    assert deployed.frontend_dir == stable / "frontend"


def test_detached_rebuild_preserves_scope_and_named_worker(lifecycle, monkeypatch):
    queue = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "queue_detached", queue)
    accepted = {
        "acceptance_id": "acceptance-test",
        "acceptance_artifact": "/tmp/acceptance-test.json",
        "source_commit": "c" * 40,
        "source_tree": "d" * 40,
    }
    monkeypatch.setattr(service_ops, "resolve_accepted_source", lambda *_args, **_kwargs: accepted)
    result = CliRunner().invoke(service.app, [
        "rebuild", "example", "--detach", "--scope", "worker", "--worker", "stopped.service",
    ])
    assert result.exit_code == 0, result.output
    queue.assert_called_once_with(
        "example",
        False,
        scope="worker",
        workers=("stopped.service",),
        accepted_source=accepted,
        with_ack=None,
        rollback=False,
    )
    lifecycle["ensure_infra"].assert_not_called()


def test_detached_rebuild_reports_local_acceptance_failure_without_traceback(lifecycle, monkeypatch):
    import subprocess

    from cli.lib import acceptance, acceptance_coordinator

    monkeypatch.setattr(acceptance, "_git_value", lambda *_args: "c" * 40)
    monkeypatch.setattr(acceptance, "_git", lambda *_args: subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(
        acceptance_coordinator,
        "accept_source",
        Mock(side_effect=acceptance.AcceptanceError("acceptance_checks_failed; TEST:FAIL:1; acceptance evidence: /tmp/check.json")),
    )
    result = CliRunner().invoke(service.app, ["rebuild", "example", "--detach"])

    assert result.exit_code == 1
    assert "TEST:FAIL:1" in result.output
    assert "/tmp/check.json" in result.output
    assert "Traceback" not in result.output


def test_detached_command_carries_scope_and_workers(monkeypatch, tmp_path):
    import json
    import subprocess

    monkeypatch.setattr(service_ops, "get_repo_root", lambda: tmp_path)
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(tmp_path / "service-state"))

    monkeypatch.setattr(service_ops, "systemctl", lambda *args: subprocess.CompletedProcess([], 3, "inactive", ""))
    capture = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(service_ops, "capture", capture)
    assert service_ops.queue_detached("example", False, scope="worker", workers=("optional.service",)) == 0
    command = capture.call_args.args[0]
    assert command[command.index("st"):command.index("st") + 3] == ["st", "service", "_run-job"]
    records = list((tmp_path / "service-state" / "jobs").glob("*.json"))
    assert len(records) == 1
    assert json.loads(records[0].read_text())["command"] == [
        "st", "service", "rebuild", "--scope", "worker", "--worker", "optional.service", "example",
    ]


def test_frontend_scope_rejects_worker_override(lifecycle):
    result = CliRunner().invoke(service.app, ["rebuild", "example", "--scope", "frontend", "--include-all-workers"])
    assert result.exit_code == 1
    lifecycle["ensure_infra"].assert_not_called()


def test_include_all_workers_explicitly_starts_optional(lifecycle, monkeypatch):
    monkeypatch.setattr(service_ops, "service_state", lambda _: "active")
    result = CliRunner().invoke(service.app, ["rebuild", "example", "--include-all-workers"])
    assert result.exit_code == 0, result.output
    assert "stopped.service" in [call.args[0] for call in lifecycle["restart_service"].call_args_list]


def test_nested_component_directory_falls_back_to_full(project, lifecycle, monkeypatch):
    monkeypatch.setattr(service, "_load", lambda _: replace(project, backend_dir=project.root))
    result = CliRunner().invoke(service.app, ["rebuild", "example", "--scope", "frontend"])
    assert result.exit_code == 0, result.output
    lifecycle["sync_backend"].assert_called_once()
    lifecycle["run_migrations"].assert_called_once()


def test_restart_keeps_scoped_restart_with_self_contained_release_build(lifecycle):
    result = CliRunner().invoke(service.app, ["restart", "example", "--scope", "backend"])
    assert result.exit_code == 0, result.output
    lifecycle["sync_backend"].assert_called_once()
    lifecycle["run_migrations"].assert_called_once()
    lifecycle["build_frontend"].assert_called_once()


def test_native_build_builds_only_workspace_dependencies_before_consumer(project):
    import json
    import subprocess

    package_manager = json.loads((service_ops.get_repo_root() / 'package.json').read_text())['packageManager']
    (project.root / 'package.json').write_text(json.dumps({'name': 'test-workspace', 'private': True, 'packageManager': package_manager}))
    (project.root / 'pnpm-workspace.yaml').write_text('packages: [frontend, packages/*]\n')
    library = project.root / 'packages/library'
    library.mkdir(parents=True)
    (library / 'package.json').write_text(json.dumps({
        'name': '@test/library', 'version': '1.0.0', 'type': 'module', 'exports': './dist/index.js',
        'scripts': {'build': 'node build.mjs'}}))
    (library / 'build.mjs').write_text("import fs from 'node:fs'; fs.mkdirSync('dist',{recursive:true}); fs.writeFileSync('dist/index.js','export const value = 42;');")
    unrelated = project.root / 'packages/unrelated'
    unrelated.mkdir()
    (unrelated / 'package.json').write_text(json.dumps({
        'name': '@test/unrelated', 'version': '1.0.0', 'scripts': {'build': 'exit 1'}}))
    project.frontend_dir.mkdir()
    (project.frontend_dir / 'package.json').write_text(json.dumps({
        'name': '@test/frontend', 'private': True, 'type': 'module',
        'scripts': {'build': 'node build.mjs'}, 'dependencies': {'@test/library': 'workspace:*'}}))
    (project.frontend_dir / 'build.mjs').write_text("import {value} from '@test/library'; if(value !== 42) process.exit(1);")
    subprocess.run(['pnpm', 'install', '--offline', '--ignore-scripts'], cwd=project.root, check=True, capture_output=True)
    before = subprocess.run(['pnpm', 'build'], cwd=project.frontend_dir, capture_output=True)
    assert before.returncode != 0
    assert b'ERR_MODULE_NOT_FOUND' in before.stderr
    assert not (library / 'dist').exists()
    assert service_ops.build_frontend(project) == 0
    assert (library / 'dist/index.js').is_file()


def test_failed_workspace_dependency_build_stops_frontend(project, monkeypatch):
    project.frontend_dir.mkdir()
    (project.frontend_dir / 'package.json').write_text('{}')
    (project.root / 'pnpm-workspace.yaml').write_text('packages: [frontend]\n')
    run = Mock(side_effect=[0, 1])
    monkeypatch.setattr(service_ops, 'run', run)
    assert service_ops.build_frontend(project) == 1
    assert run.call_count == 2
    assert run.call_args.args[0][-3:] == ['--if-present', 'run', 'build']


def test_host_monitor_build_prefers_rustup_cargo(tmp_path, monkeypatch) -> None:
    cargo = tmp_path / "bin" / "cargo"
    cargo.parent.mkdir()
    cargo.write_text("#!/bin/sh\n")
    cargo.chmod(0o755)
    monkeypatch.setenv("CARGO_HOME", str(tmp_path))
    assert service_ops._cargo() == str(cargo)
    monkeypatch.setenv("CARGO_HOME", str(tmp_path / "missing"))
    assert service_ops._cargo() == "cargo"


@pytest.mark.parametrize("unit, shown, expected, stopped", [
    ("example-smoke-1.service", "LoadState=loaded\nTransient=yes\nActiveState=active\n", "stopped", True),
    ("example-harness.scope", "LoadState=loaded\nTransient=yes\nActiveState=inactive\n", "already_inactive", False),
    ("example-gone.service", "LoadState=not-found\nTransient=no\nActiveState=inactive\n", "absent", False),
    ("example-persistent.service", "LoadState=loaded\nTransient=no\nActiveState=active\n", "refused:not_transient", False),
    ("backend.service", None, "refused:name_outside_example-*.service|.scope", False),
    ("other-smoke.service", None, "refused:name_outside_example-*.service|.scope", False),
    ("example-x.timer", None, "refused:name_outside_example-*.service|.scope", False),
    ("example--help.service; true", None, "refused:name_outside_example-*.service|.scope", False),
])
def test_stop_unit_only_stops_project_transient_units(monkeypatch, project, unit, shown, expected, stopped):
    calls = []

    def systemctl(*args):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, shown if args[0] == "show" else "", "")

    monkeypatch.setattr(service_ops, "systemctl", systemctl)
    monkeypatch.setattr(service, "_load", lambda _: project)
    result = CliRunner().invoke(service.app, ["stop-unit", "example", unit])
    assert f"state={expected}" in result.output
    assert result.exit_code == (2 if expected.startswith("refused") else 0)
    assert (("stop", "--", unit) in calls) is stopped
    if shown is None:
        assert calls == []


def test_stop_unit_refuses_managed_service_with_project_prefix(monkeypatch, project):
    monkeypatch.setattr(service_ops, "systemctl", Mock(side_effect=AssertionError("no systemctl")))
    managed = replace(project, optional_workers=("example-worker.service",))
    code, state = service_ops.stop_transient_unit(managed, "example-worker.service")
    assert (code, state) == (2, "refused:managed_service;use_st_service_stop")


@pytest.mark.parametrize("failure", [FileNotFoundError(2, "CA bundle vanished"), KeyboardInterrupt()])
def test_unexpected_failure_after_collector_activation_rolls_back_collector(
    lifecycle, monkeypatch, failure
):
    """Regression: a raw OSError in health checks stranded the activated collector."""
    deployments: list[str] = []
    monkeypatch.setattr(service_ops, "has_host_monitor", lambda _project: True)
    monkeypatch.setattr(service_ops, "preflight_host_monitor", lambda _project: 0)
    monkeypatch.setattr(service_ops, "build_host_monitor", lambda _project: 0)
    monkeypatch.setattr(service_ops, "sync_host_monitor_policy", lambda _project: 0)
    monkeypatch.setattr(service_ops, "verify_host_monitor", lambda _project: 0)
    monkeypatch.setattr(service_ops, "host_monitor_deployment",
                        lambda _project, _build, action: deployments.append(action) or 0)
    monkeypatch.setattr(service, "_restore_previous_units", lambda *_args: True)
    lifecycle["verify_health"].side_effect = failure

    result = CliRunner().invoke(service.app, ["rebuild", "example"])

    assert result.exit_code != 0
    assert deployments == ["install", "rollback"]
    fail_release = service_release.fail_release
    assert isinstance(fail_release, Mock)
    assert fail_release.call_args.args[1] == "deployment"


def test_collector_rollback_falls_back_when_reader_restore_raises(lifecycle, monkeypatch):
    deployments: list[str] = []
    monkeypatch.setattr(service_ops, "has_host_monitor", lambda _project: True)
    monkeypatch.setattr(service_ops, "preflight_host_monitor", lambda _project: 0)
    monkeypatch.setattr(service_ops, "build_host_monitor", lambda _project: 0)
    monkeypatch.setattr(service_ops, "sync_host_monitor_policy", lambda _project: 0)
    monkeypatch.setattr(service_ops, "verify_host_monitor", lambda _project: 0)
    monkeypatch.setattr(service_ops, "host_monitor_deployment",
                        lambda _project, _build, action: deployments.append(action) or 0)

    def broken_restore(*_args):
        raise ImportError("backend environment damaged")

    monkeypatch.setattr(service, "_restore_previous_units", broken_restore)
    lifecycle["verify_health"].side_effect = OSError("damaged runtime")

    result = CliRunner().invoke(service.app, ["rebuild", "example"])

    assert result.exit_code != 0
    assert deployments == ["install", "rollback"]
    assert "rolling back collector directly" in result.output


@pytest.fixture
def activated(project):
    return replace(project, backend_service="", backend_port=0, frontend_service="web.socket",
                   frontend_port=3022, default_workers=("reaper.timer",), optional_workers=())


def test_activation_units_sync_their_paired_service_templates(activated, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    templates = activated.root / "scripts" / "systemd"
    templates.mkdir(parents=True)
    for name in ("web.socket", "web.service", "reaper.timer", "reaper.service"):
        (templates / name).write_text("ExecStart=__PROJECT_ROOT__/run\n")
    monkeypatch.setattr(service_ops, "run", lambda *args, **kwargs: 0)
    assert service_ops.sync_systemd_units(activated) == 0
    units = tmp_path / "config" / "systemd" / "user"
    assert sorted(path.name for path in units.iterdir()) == [
        "reaper.service", "reaper.timer", "web.service", "web.socket"]
    assert (units / "web.service").read_text() == f"ExecStart={activated.root}/run\n"


def test_activation_unit_restart_stops_paired_service_and_never_kills_the_socket_port(monkeypatch):
    commands = []
    monkeypatch.setattr(service_ops, "service_exists", lambda _: True)
    monkeypatch.setattr(service_ops, "run", lambda command, **_: commands.append(command[2:]) or 0)
    monkeypatch.setattr(service_ops, "_wait_service_inactive", lambda _: True)
    monkeypatch.setattr(service_ops, "service_state", lambda _: "active")
    monkeypatch.setattr(service_ops, "_kill_port", lambda _: pytest.fail("socket listener must stay with systemd"))
    assert service_ops.restart_service("web.socket", port=3022) == 0
    assert commands == [["enable", "web.socket"], ["stop", "web.socket"],
                        ["stop", "web.service"], ["start", "web.socket"]]


def test_activation_unit_start_enables_and_stop_stops_both(activated, monkeypatch):
    commands = []
    monkeypatch.setattr(service_ops.service_release, "current_source_root", lambda _: None)
    monkeypatch.setattr(service_ops, "sync_systemd_units", lambda _: 0)
    monkeypatch.setattr(service_ops, "service_exists", lambda _: True)
    monkeypatch.setattr(service_ops, "run", lambda command, **_: commands.append(command[-2:]) or 0)
    assert service_ops.start_services(activated) == 0
    assert commands == [["enable", "web.socket"], ["start", "web.socket"],
                        ["enable", "reaper.timer"], ["start", "reaper.timer"]]
    commands.clear()
    assert service_ops.stop_services(activated) == 0
    assert commands == [["stop", "reaper.timer"], ["stop", "reaper.service"],
                        ["stop", "web.socket"], ["stop", "web.service"]]


@pytest.mark.parametrize(("paired_state", "code"), [("inactive", 0), ("active", 0), ("failed", 1)])
def test_activation_unit_status_reports_paired_service(activated, monkeypatch, paired_state, code):
    monkeypatch.setattr(service, "_load", lambda _: activated)
    monkeypatch.setattr(service_ops, "service_state",
                        lambda name: paired_state if name.endswith(".service") else "active")
    result = CliRunner().invoke(service.app, ["status", "example"])
    assert result.exit_code == code, result.output
    assert f"web.socket:active(web.service:{paired_state})" in result.output
    assert f"reaper.timer:active(reaper.service:{paired_state})" in result.output


def test_release_installer_runs_after_units_and_before_restart(lifecycle, monkeypatch, project):
    order: list[str] = []
    installing = replace(project, release_install="deploy/install.sh")
    monkeypatch.setattr(service, "_load", lambda _: installing)
    lifecycle["sync_systemd_units"].side_effect = lambda _p: order.append("units") or 0
    lifecycle["restart_service"].side_effect = lambda *_a, **_k: order.append("restart") or 0
    install = Mock(side_effect=lambda *_a, **_k: order.append("install") or 0)
    monkeypatch.setattr(service_ops, "run_release_install", install)

    result = CliRunner().invoke(service.app, ["rebuild", "example"])

    assert result.exit_code == 0, result.output
    assert order[:3] == ["units", "install", "restart"]
    assert install.call_args.kwargs == {"development_root": project.root, "source_commit": "c" * 40}


def test_failed_release_installer_stops_before_restart(lifecycle, monkeypatch, project):
    monkeypatch.setattr(service, "_load", lambda _: replace(project, release_install="deploy/install.sh"))
    monkeypatch.setattr(service_ops, "run_release_install", Mock(return_value=1))

    result = CliRunner().invoke(service.app, ["rebuild", "example"])

    assert result.exit_code != 0
    assert "release install failed" in result.output
    lifecycle["restart_service"].assert_not_called()


def test_release_installer_gets_development_root_and_commit(project, tmp_path):
    script = project.root / "deploy" / "install.sh"
    script.parent.mkdir()
    script.write_text('#!/bin/sh\necho "$ST_DEVELOPMENT_ROOT $ST_SOURCE_COMMIT $(pwd)" > "$0.out"\n')
    installing = replace(project, release_install="deploy/install.sh")

    script.chmod(0o644)
    assert service_ops.run_release_install(installing, development_root=Path("/dev/repo"), source_commit="abc") == 1
    script.chmod(0o755)
    assert service_ops.run_release_install(installing, development_root=Path("/dev/repo"), source_commit="abc") == 0
    assert (script.parent / "install.sh.out").read_text().split() == ["/dev/repo", "abc", str(project.root.resolve())]
    assert service_ops.run_release_install(project, development_root=Path("/x"), source_commit="abc") == 0


@pytest.mark.parametrize("value", ["../elsewhere.sh", "/usr/bin/true", 3])
def test_release_installer_must_live_inside_the_project(monkeypatch, tmp_path, value):
    monkeypatch.setattr(service_ops, "get_project_identity", lambda _: {"runtime": {"release_install": value}})
    monkeypatch.setattr(service_ops, "get_project_identity_root", lambda _: str(tmp_path))
    with pytest.raises(service_ops.ServiceError, match="release_install"):
        service_ops.load_project("example")


def _mock(patched: object) -> Mock:
    assert isinstance(patched, Mock)
    return patched


def _phases() -> list[tuple[str, str | None]]:
    return [(call.args[1], call.kwargs.get("status")) for call in _mock(service_release.mark_phase).call_args_list]


def test_full_rebuild_marks_release_phases_in_order(lifecycle):
    result = CliRunner().invoke(service.app, ["rebuild", "example"])

    assert result.exit_code == 0, result.output
    assert _phases() == [
        ("deployment_scope", "selected"), ("infrastructure", "succeeded"),
        ("backend_dependencies", "succeeded"), ("host_monitor_build", "succeeded"),
        ("frontend_build", "succeeded"), ("migrations", "succeeded"), ("systemd_units", "succeeded"),
        ("host_monitor_policy", "succeeded"), ("restart", "succeeded"), ("health", "succeeded"),
        ("seeds", "succeeded"),
    ]
    restart = _mock(service_release.mark_phase).call_args_list[-3]
    assert restart.kwargs["services"] == ["backend.service", "required.service", "active.service", "frontend.service"]
    _mock(service_release.fail_release).assert_not_called()
    _mock(service_release.complete_release).assert_called_once()
    assert "[service] worker required.service: active" in result.output


def test_frontend_rebuild_marks_migrations_not_applicable_in_sequence(lifecycle):
    result = CliRunner().invoke(service.app, ["rebuild", "example", "--scope", "frontend"])

    assert result.exit_code == 0, result.output
    assert _phases() == [
        # Recorded while the step list is built, before any step runs.
        ("deployment_scope", "selected"), ("migrations", "not_applicable"),
        ("infrastructure", "succeeded"), ("backend_dependencies", "succeeded"),
        ("frontend_build", "succeeded"), ("systemd_units", "succeeded"), ("restart", "succeeded"),
        ("health", "succeeded"), ("seeds", "succeeded"),
    ]
    restarted = [call.args[0] for call in lifecycle["restart_service"].call_args_list]
    assert restarted == ["frontend.service"]


def test_seed_failure_fails_release_after_health(lifecycle, monkeypatch):
    restore = Mock(return_value=True)
    monkeypatch.setattr(service, "_restore_previous_units", restore)
    lifecycle["sync_seeds"].return_value = 1

    result = CliRunner().invoke(service.app, ["rebuild", "example"])

    assert result.exit_code == 1
    assert _phases()[-3:] == [("restart", "succeeded"), ("health", "succeeded"), ("seeds", "failed")]
    restore.assert_called_once()
    _mock(service_release.fail_release).assert_called_once()
    assert _mock(service_release.fail_release).call_args.args[1] == "restart_health"
    assert _mock(service_release.fail_release).call_args.kwargs == {
        "migrations": "applied; automatic database rollback is unsupported"}
    assert "rebuild completed with 1 error(s)" in result.output
    _mock(service_release.complete_release).assert_not_called()


def test_restart_failure_skips_seeds_and_reports_every_error(lifecycle, monkeypatch):
    monkeypatch.setattr(service, "_restore_previous_units", Mock(return_value=True))
    lifecycle["restart_service"].side_effect = lambda name, **_kwargs: int(name == "backend.service")
    lifecycle["verify_health"].return_value = 1

    result = CliRunner().invoke(service.app, ["rebuild", "example"])

    assert result.exit_code == 1
    assert _phases()[-2:] == [("restart", "failed"), ("health", "failed")]
    lifecycle["sync_seeds"].assert_not_called()
    assert "rebuild completed with 2 error(s)" in result.output


def test_failed_unit_sync_restores_units_and_stops_before_restart(lifecycle, monkeypatch):
    restore = Mock(return_value=True)
    monkeypatch.setattr(service, "_restore_previous_units", restore)
    lifecycle["sync_systemd_units"].return_value = 1

    result = CliRunner().invoke(service.app, ["rebuild", "example"])

    assert result.exit_code == 1
    assert _phases()[-1] == ("systemd_units", "failed")
    restore.assert_called_once()
    assert _mock(service_release.fail_release).call_args_list[0].args[1] == "systemd_units"
    assert "rebuild stopped: systemd units failed; services were not restarted" in result.output
    lifecycle["restart_service"].assert_not_called()


def test_failed_build_step_does_not_restore_units(lifecycle, monkeypatch):
    restore = Mock(return_value=True)
    monkeypatch.setattr(service, "_restore_previous_units", restore)
    lifecycle["build_frontend"].return_value = 1

    result = CliRunner().invoke(service.app, ["rebuild", "example"])

    assert result.exit_code == 1
    assert _phases()[-1] == ("frontend_build", "failed")
    restore.assert_not_called()
    lifecycle["run_migrations"].assert_not_called()


@pytest.fixture
def collector(lifecycle, monkeypatch, project):
    deployments: list[str] = []
    monkeypatch.setattr(service, "_load", lambda _: replace(project, project_id="summitflow"))
    monkeypatch.setattr(service_ops, "has_host_monitor", lambda _project: True)
    monkeypatch.setattr(service_ops, "preflight_host_monitor", lambda _project: 0)
    monkeypatch.setattr(service_ops, "verify_host_monitor", lambda _project: 0)
    monkeypatch.setattr(service_ops, "host_monitor_deployment",
                        lambda _project, _build, action: deployments.append(action) or 0)
    monkeypatch.setattr(service, "backup_worker_restart_guard", lambda: nullcontext(lambda: None))
    rollback = Mock(return_value=True)
    monkeypatch.setattr(service, "_rollback_monitor_and_reader", rollback)
    return SimpleNamespace(deployments=deployments, rollback=rollback)


def test_collector_rollback_after_health_failure_restarts_previous_reader(lifecycle, collector):
    lifecycle["verify_health"].return_value = 1

    result = CliRunner().invoke(service.app, ["rebuild", "summitflow"])

    assert result.exit_code == 1
    assert collector.deployments == ["install"]
    collector.rollback.assert_called_once()
    assert collector.rollback.call_args.args[3] is True
    assert _mock(service_release.fail_release).call_args.args[1] == "restart_health"


def test_guard_loss_at_backend_restart_still_counts_restart_as_attempted(
    lifecycle, collector, monkeypatch
):
    from app.tasks.backup_lock import BackupLockLeaseError

    def assert_owned():
        if collector.deployments:
            raise BackupLockLeaseError("backup started")

    monkeypatch.setattr(service, "backup_worker_restart_guard", lambda: nullcontext(assert_owned))

    result = CliRunner().invoke(service.app, ["rebuild", "summitflow"])

    assert result.exit_code == 1
    lifecycle["restart_service"].assert_not_called()
    collector.rollback.assert_called_once()
    assert collector.rollback.call_args.args[3] is True
    assert _mock(service_release.fail_release).call_args.args[1] == "deployment"


def test_collector_verification_failure_rolls_back_without_reader_restart(lifecycle, collector, monkeypatch):
    monkeypatch.setattr(service_ops, "verify_host_monitor", lambda _project: 1)

    result = CliRunner().invoke(service.app, ["rebuild", "summitflow"])

    assert result.exit_code == 1
    assert "root collector activation failed verification" in result.output
    lifecycle["restart_service"].assert_not_called()
    collector.rollback.assert_called_once()
    assert collector.rollback.call_args.args[3] is False


def test_activated_collector_is_listed_as_restarted_without_a_unit_restart(
    lifecycle, collector, monkeypatch, project
):
    monitor = "summitflow-host-monitor.service"
    monkeypatch.setattr(service, "_load", lambda _: replace(
        project, project_id="summitflow", default_workers=(monitor,), optional_workers=()))
    for name in ("build_host_monitor", "sync_host_monitor_policy", "install_st_monitor_launcher"):
        monkeypatch.setattr(service_ops, name, lambda _project: 0)

    result = CliRunner().invoke(service.app, ["rebuild", "summitflow"])

    assert result.exit_code == 0, result.output
    assert collector.deployments == ["install", "finalize"]
    restarted = [call.args[0] for call in lifecycle["restart_service"].call_args_list]
    assert monitor not in restarted
    assert restarted == ["backend.service", "frontend.service"]
    restart = next(call for call in _mock(service_release.mark_phase).call_args_list if call.args[1] == "restart")
    assert restart.kwargs["services"] == ["backend.service", monitor, "frontend.service"]
    collector.rollback.assert_not_called()
