"""Regression coverage for managed lifecycle selection and failure reporting."""

import subprocess
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from cli.commands import service
from cli.lib import service_ops, service_release


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
        service_ops, "prepare_accepted_release", lambda current, _receipt=None: (release, current)
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


def test_migrations_use_host_project_database_env_from_accepted_source(
    project, monkeypatch, tmp_path
):
    accepted_root = tmp_path / "release" / "source"
    backend_dir = accepted_root / "backend"
    (backend_dir / ".venv" / "bin").mkdir(parents=True)
    (backend_dir / "alembic.ini").touch()
    (backend_dir / ".venv" / "bin" / "alembic").touch()
    (accepted_root / ".env").write_text("PORTFOLIO_DB_URL=postgresql://source-stale\n")
    host_root = tmp_path / "host-checkout"
    host_root.mkdir()
    (host_root / ".env").write_text("PORTFOLIO_DB_URL=postgresql://host-base\n")
    (host_root / ".env.local").write_text(
        "PORTFOLIO_DB_URL=postgresql://host-local\n"
        "JOBINATOR_DB_URL=postgresql://jobinator-host\n"
        "INTERNAL_SERVICE_SECRET=host-secret-not-for-migrations\n"
    )
    deployed = replace(
        project,
        project_id="portfolio-ai",
        root=accepted_root,
        backend_dir=backend_dir,
        frontend_dir=accepted_root / "frontend",
        host_config_root=host_root,
    )
    monkeypatch.setenv("PORTFOLIO_DB_URL", "postgresql://stale-shell")
    monkeypatch.setenv("DATABASE_URL", "postgresql://other-project")
    monkeypatch.setenv("JOBINATOR_DB_URL", "postgresql://jobinator-stale-shell")
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET", raising=False)
    run = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "run", run)

    assert service_ops.run_migrations(deployed) == 0
    migration_env = run.call_args.kwargs["env"]
    assert migration_env["PORTFOLIO_DB_URL"] == "postgresql://host-local"
    assert "JOBINATOR_DB_URL" not in migration_env
    assert "DATABASE_URL" not in migration_env
    assert "INTERNAL_SERVICE_SECRET" not in migration_env
    assert run.call_args.kwargs["cwd"] == backend_dir


def test_neri_migrations_use_approved_operator_db_env(project, monkeypatch, tmp_path):
    backend_dir = tmp_path / "release" / "backend"
    (backend_dir / ".venv" / "bin").mkdir(parents=True)
    (backend_dir / "alembic.ini").touch()
    (backend_dir / ".venv" / "bin" / "alembic").touch()
    operator_home = tmp_path / "operator"
    operator_home.mkdir()
    (operator_home / ".env.local").write_text(
        "NERI_DB_URL=postgresql://approved-neri\n"
        "PORTFOLIO_DB_URL=postgresql://other-project\n"
        "INTERNAL_SERVICE_SECRET=not-for-migrations\n"
    )
    monkeypatch.setattr(service_ops.Path, "home", lambda: operator_home)
    run = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "run", run)
    deployed = replace(project, project_id="neri", backend_dir=backend_dir)

    assert service_ops.run_migrations(deployed) == 0
    migration_env = run.call_args.kwargs["env"]
    assert migration_env["NERI_DB_URL"] == "postgresql://approved-neri"
    assert "PORTFOLIO_DB_URL" not in migration_env
    assert "INTERNAL_SERVICE_SECRET" not in migration_env


def test_jobinator_migrations_use_approved_operator_db_env(project, monkeypatch, tmp_path):
    backend_dir = tmp_path / "release" / "backend"
    (backend_dir / ".venv" / "bin").mkdir(parents=True)
    (backend_dir / "alembic.ini").touch()
    (backend_dir / ".venv" / "bin" / "alembic").touch()
    operator_home = tmp_path / "operator"
    operator_home.mkdir()
    (operator_home / ".env.local").write_text(
        "JOBINATOR_DB_URL=postgresql://approved-jobinator\n"
        "NERI_DB_URL=postgresql://other-project\n"
        "INTERNAL_SERVICE_SECRET=not-for-migrations\n"
    )
    monkeypatch.setattr(service_ops.Path, "home", lambda: operator_home)
    run = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "run", run)
    deployed = replace(project, project_id="jobinator-4000", backend_dir=backend_dir)

    assert service_ops.run_migrations(deployed) == 0
    migration_env = run.call_args.kwargs["env"]
    assert migration_env["JOBINATOR_DB_URL"] == "postgresql://approved-jobinator"
    assert "NERI_DB_URL" not in migration_env
    assert "INTERNAL_SERVICE_SECRET" not in migration_env


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
    monkeypatch.setattr(service_ops, "resolve_accepted_source", lambda *_args: accepted)
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
    )
    lifecycle["ensure_infra"].assert_not_called()


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
