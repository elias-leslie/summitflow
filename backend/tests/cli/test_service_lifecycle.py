"""Regression coverage for managed lifecycle selection and failure reporting."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from cli.commands import service
from cli.lib import service_ops


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
    assert lifecycle["build_frontend"].call_count == int(scope == "frontend")


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


def test_detached_rebuild_preserves_scope_and_named_worker(lifecycle, monkeypatch):
    queue = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "queue_detached", queue)
    result = CliRunner().invoke(service.app, [
        "rebuild", "example", "--detach", "--scope", "worker", "--worker", "stopped.service",
    ])
    assert result.exit_code == 0, result.output
    queue.assert_called_once_with("example", False, scope="worker", workers=("stopped.service",))
    lifecycle["ensure_infra"].assert_not_called()


def test_detached_command_carries_scope_and_workers(monkeypatch, tmp_path):
    import json
    import subprocess

    monkeypatch.setattr(service_ops, "get_repo_root", lambda: tmp_path)

    monkeypatch.setattr(service_ops, "systemctl", lambda *args: subprocess.CompletedProcess([], 3, "inactive", ""))
    capture = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(service_ops, "capture", capture)
    assert service_ops.queue_detached("example", False, scope="worker", workers=("optional.service",)) == 0
    command = capture.call_args.args[0]
    assert command[command.index("st"):command.index("st") + 3] == ["st", "service", "_run-job"]
    records = list((tmp_path / ".dev-tools" / "service-jobs").glob("*.json"))
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


def test_restart_keeps_rebuild_and_scope_contract(lifecycle):
    result = CliRunner().invoke(service.app, ["restart", "example", "--scope", "backend"])
    assert result.exit_code == 0, result.output
    lifecycle["sync_backend"].assert_called_once()
    lifecycle["run_migrations"].assert_called_once()
    lifecycle["build_frontend"].assert_not_called()


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
