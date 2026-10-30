"""Regression coverage for managed lifecycle selection and failure reporting."""

import json
import os
import shutil
import subprocess
import sys
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
def runtime(project, tmp_path, monkeypatch):
    """An expected main PID and a child listener in one user-manager unit."""
    source = tmp_path / "release" / "source"
    project = replace(project, root=source, backend_dir=source / "backend", frontend_dir=source / "frontend")
    proc = tmp_path / "proc"
    project.backend_dir.mkdir(parents=True)
    uid = os.getuid()
    cgroup = f"/user.slice/user-{uid}.slice/user@{uid}.service/app.slice/backend.service"
    properties = {"Id": project.backend_service, "LoadState": "loaded", "ActiveState": "active",
                  "MainPID": "11", "ControlGroup": cgroup, "WorkingDirectory": str(project.backend_dir)}
    for pid in (11, 12):
        process = proc / str(pid)
        process.mkdir(parents=True)
        (process / "cwd").symlink_to(project.backend_dir, target_is_directory=True)
        (process / "status").write_text(f"Uid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
        (process / "cgroup").write_text(f"0::{cgroup}\n")
    monkeypatch.setattr(service_ops, "_PROC_ROOT", proc, raising=False)
    monkeypatch.setattr(service_ops, "systemctl", lambda *args: subprocess.CompletedProcess(
        args, 0, "\n".join(f"{key}={value}" for key, value in properties.items()), ""))
    listeners = Mock(return_value=subprocess.CompletedProcess([], 0, 'LISTEN users:(("python",pid=12,fd=4))\n', ""))
    monkeypatch.setattr(service_ops, "capture", listeners)
    monkeypatch.setattr(service_ops.time, "sleep", lambda _: None)
    http = Mock(return_value=SimpleNamespace(status_code=200))
    monkeypatch.setattr(service_ops.httpx, "get", http)
    return replace(project, frontend_service=""), proc, properties, listeners, http


def test_health_accepts_a_listener_child_of_the_expected_release_unit(runtime):
    project, _proc, _properties, _listeners, http = runtime
    assert service_ops.verify_health(project) == 0
    http.assert_called_once()


@pytest.mark.parametrize("mismatch", ["", "scope_pid", "inactive", "persistent", "scope_group",
                                      "membership", "invocation", "listener", "source", "uid"])
def test_desktop_main_pid_can_move_to_its_verified_gnome_application_scope(runtime, tmp_path, monkeypatch, mismatch):
    project, proc, properties, _listeners, http = runtime
    uid = os.getuid()
    scope = "app-example-11.scope"
    group = f"/user.slice/user-{uid}.slice/user@{uid}.service/app.slice/{scope}"
    for pid in (11, 12):
        (proc / str(pid) / "cgroup").write_text(f"0::{group}\n")
    cgroups = tmp_path / "cgroups"
    directory = cgroups / group.lstrip("/")
    directory.mkdir(parents=True)
    (directory / "cgroup.procs").write_text("11\n12\n")
    scope_properties = {"Id": scope, "LoadState": "loaded", "ActiveState": "active",
                        "ControlGroup": group, "Transient": "yes", "InvocationID": "a" * 32}
    if mismatch == "scope_pid":
        (proc / "11/cgroup").write_text(f"0::{group.replace('-11.scope', '-99.scope')}\n")
    elif mismatch == "inactive":
        scope_properties["ActiveState"] = "inactive"
    elif mismatch == "persistent":
        scope_properties["Transient"] = "no"
    elif mismatch == "scope_group":
        scope_properties["ControlGroup"] = properties["ControlGroup"]
    elif mismatch == "membership":
        (directory / "cgroup.procs").write_text("12\n")
    elif mismatch == "invocation":
        scope_properties["InvocationID"] = ""
    elif mismatch == "listener":
        (proc / "12/cgroup").write_text("0::/foreign.service\n")
    elif mismatch == "source":
        (proc / "11/cwd").unlink()
        (proc / "11/cwd").symlink_to(tmp_path, target_is_directory=True)
    elif mismatch == "uid":
        (proc / "11/status").write_text("Uid:\t99999\t99999\t99999\t99999\n")
    monkeypatch.setattr(service_ops, "_CGROUP_ROOT", cgroups, raising=False)

    def systemctl(*args):
        values = scope_properties if args[1] == scope else properties
        return subprocess.CompletedProcess(args, 0, "\n".join(f"{key}={value}" for key, value in values.items()), "")

    monkeypatch.setattr(service_ops, "systemctl", systemctl)
    assert service_ops.verify_health(project) == int(bool(mismatch))
    assert http.called is (not mismatch)


def test_named_runtime_health_resolves_the_configured_login(runtime, monkeypatch):
    project, _proc, _properties, _listeners, http = runtime
    lookup = Mock(side_effect=lambda login: SimpleNamespace(pw_uid=os.getuid()) if login == "actual-login" else
                  (_ for _ in ()).throw(KeyError(login)))
    monkeypatch.setattr(service_ops.pwd, "getpwnam", lookup)
    assert service_ops.verify_health(replace(project, runtime_user="actual-login")) == 0
    assert lookup.call_args.args == ("actual-login",)
    http.assert_called_once()


def test_suffixless_unit_attestation_uses_the_canonical_systemd_id(runtime):
    project, _proc, _properties, _listeners, http = runtime
    assert service_ops.verify_health(replace(project, backend_service="backend")) == 0
    http.assert_called_once()


@pytest.mark.parametrize("mismatch", ["", "old_commit", "missing_commit", "foreign_uid", "foreign_listener"])
def test_installer_runtime_attests_the_launched_commit_outside_materialized_source(runtime, tmp_path, mismatch):
    project, proc, properties, _listeners, http = runtime
    project = replace(project, backend_service="backend", release_install="deploy/systemd/install.sh", source_sha="a" * 40)
    # Nightshift's installed unit has no WorkingDirectory and starts an
    # interpreter in current-venv through its stable bin/nightshift launcher.
    home = tmp_path / "home"
    home.mkdir()
    properties["WorkingDirectory"] = ""
    for pid in (11, 12):
        (proc / str(pid) / "cwd").unlink()
        (proc / str(pid) / "cwd").symlink_to(home, target_is_directory=True)
        (proc / str(pid) / "environ").write_bytes(b"SUMMITFLOW_SOURCE_SHA=" + b"a" * 40 + b"\0")
    if mismatch == "old_commit":
        (proc / "11/environ").write_bytes(b"SUMMITFLOW_SOURCE_SHA=" + b"b" * 40 + b"\0")
    elif mismatch == "missing_commit":
        (proc / "11/environ").write_bytes(b"PATH=/fixture/bin\0")
    elif mismatch == "foreign_uid":
        (proc / "11/status").write_text("Uid:\t99999\t99999\t99999\t99999\n")
    elif mismatch == "foreign_listener":
        (proc / "12/cgroup").write_text("0::/foreign.service\n")
    assert service_ops.verify_health(project) == int(bool(mismatch))
    assert http.called is (not mismatch)


@pytest.mark.parametrize("mismatch", ["foreign_listener", "foreign_uid", "old_release", "main_release",
                                      "manager_uid", "inactive", "missing_pid", "unreadable_listener",
                                      "hidden_listener", "missing_cgroup", "working_directory", "ss_unavailable"])
def test_http_success_cannot_accept_an_unattested_runtime(runtime, tmp_path, mismatch):
    project, proc, properties, listeners, http = runtime
    if mismatch == "foreign_listener":
        (proc / "12/cgroup").write_text("0::/foreign.service\n")
    elif mismatch == "foreign_uid":
        (proc / "12/status").write_text("Uid:\t99999\t99999\t99999\t99999\n")
    elif mismatch in {"old_release", "main_release"}:
        old = tmp_path / "previous-release"
        old.mkdir()
        cwd = proc / ("11/cwd" if mismatch == "main_release" else "12/cwd")
        cwd.unlink()
        cwd.symlink_to(old, target_is_directory=True)
    elif mismatch == "manager_uid":
        properties["ControlGroup"] = "/user.slice/user-99999.slice/user@99999.service/app.slice/backend.service"
    elif mismatch == "inactive":
        properties["ActiveState"] = "failed"
    elif mismatch == "missing_pid":
        properties["MainPID"] = "0"
    elif mismatch == "hidden_listener":
        listeners.return_value.stdout += "LISTEN 0 128 127.0.0.1:8001 *:*\n"
    elif mismatch == "missing_cgroup":
        (proc / "11/cgroup").unlink()
    elif mismatch == "working_directory":
        properties["WorkingDirectory"] = str(tmp_path)
    elif mismatch == "ss_unavailable":
        listeners.side_effect = FileNotFoundError("ss")
    else:
        listeners.return_value = subprocess.CompletedProcess([], 0, "LISTEN 0 128 127.0.0.1:8001 *:*\n", "")
    assert service_ops.verify_health(project) == 1
    http.assert_not_called()


def test_health_requires_the_routed_manager_uid(runtime, monkeypatch):
    project, _proc, _properties, _listeners, http = runtime
    monkeypatch.setattr(service_ops.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=os.getuid() + 1))
    assert service_ops.verify_health(replace(project, runtime_user="svc")) == 1
    http.assert_not_called()


def test_health_attests_frontend_processes_too(runtime):
    project, proc, _properties, _listeners, http = runtime
    frontend = replace(project, frontend_service=project.backend_service, frontend_port=project.backend_port,
                       backend_service="")
    (proc / "12/cgroup").write_text("0::/foreign.service\n")
    assert service_ops.verify_health(frontend) == 1
    http.assert_not_called()


@pytest.mark.parametrize("port_matches", [True, False])
def test_socket_health_attests_the_paired_release_and_shared_manager(runtime, tmp_path, monkeypatch, port_matches):
    project, proc, properties, listeners, _http = runtime
    manager_group = properties["ControlGroup"].rsplit("/app.slice/", 1)[0]
    manager = proc / "13"
    manager.mkdir()
    (manager / "status").write_text((proc / "12/status").read_text())
    (manager / "cgroup").write_text(f"0::{manager_group}\n")
    executable = tmp_path / "systemd"
    executable.touch()
    (manager / "exe").symlink_to(executable)
    listeners.return_value.stdout = 'LISTEN users:(("app",pid=12,fd=4),("systemd",pid=13,fd=5))\n'
    monkeypatch.setattr(service_ops, "_systemctl_value", lambda *_: f"127.0.0.1:{8001 if port_matches else 9999} (Stream)")
    monkeypatch.setattr(service_ops, "service_state", lambda _: "active")
    assert service_ops.verify_health(replace(project, backend_service="backend.socket")) == int(not port_matches)


def test_health_rechecks_listener_identity_after_the_response(runtime):
    project, proc, _properties, _listeners, http = runtime

    def changed_listener(*_args, **_kwargs):
        (proc / "12/cgroup").write_text("0::/foreign.service\n")
        return SimpleNamespace(status_code=200)

    http.side_effect = changed_listener
    assert service_ops.verify_health(project) == 1


def test_restart_refuses_a_foreign_listener_before_service_mutation(runtime, monkeypatch):
    project, proc, _properties, _listeners, _http = runtime
    (proc / "12/cgroup").write_text("0::/foreign.service\n")
    monkeypatch.setattr(service_ops, "service_exists", lambda _: True)
    monkeypatch.setattr(service_ops, "_port_open", lambda _: True)
    run = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "run", run)
    assert service_ops.restart_service(project.backend_service, port=project.backend_port, project=project) == 1
    run.assert_not_called()


def test_restart_rejects_a_successful_start_from_the_previous_release(runtime, tmp_path, monkeypatch):
    project, proc, _properties, _listeners, _http = runtime
    previous = tmp_path / "previous"
    previous.mkdir()
    (proc / "11/cwd").unlink()
    (proc / "11/cwd").symlink_to(previous, target_is_directory=True)
    monkeypatch.setattr(service_ops, "service_exists", lambda _: True)
    monkeypatch.setattr(service_ops, "_service_main_pid", lambda _: 11)
    monkeypatch.setattr(service_ops, "_port_open", lambda _: False)
    monkeypatch.setattr(service_ops, "_pid_alive", lambda _: False)
    monkeypatch.setattr(service_ops, "_wait_service_inactive", lambda _: True)
    monkeypatch.setattr(service_ops, "_wait_service_active", lambda _: True)
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    run = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "run", run)
    assert service_ops.restart_service(project.backend_service, port=project.backend_port, project=project) == 1
    assert run.call_args.args[0][-2:] == ["start", project.backend_service]


def test_worker_restart_rejects_an_active_previous_release(runtime, tmp_path, monkeypatch):
    project, proc, _properties, _listeners, _http = runtime
    previous = tmp_path / "previous"
    previous.mkdir()
    (proc / "11/cwd").unlink()
    (proc / "11/cwd").symlink_to(previous, target_is_directory=True)
    monkeypatch.setattr(service_ops, "service_exists", lambda _: True)
    monkeypatch.setattr(service_ops, "_service_main_pid", lambda _: 11)
    monkeypatch.setattr(service_ops, "_pid_alive", lambda _: False)
    monkeypatch.setattr(service_ops, "_wait_service_inactive", lambda _: True)
    monkeypatch.setattr(service_ops, "_wait_service_active", lambda _: True)
    monkeypatch.setattr(service_ops, "run", Mock(return_value=0))
    mark_phase = Mock()
    monkeypatch.setattr(service_release, "mark_phase", mark_phase)
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    assert service._restart_services(
        project, Mock(), (project.backend_service,), restart_backend=False, frontend=False,
        monitor_activated=False,
    ) == 1
    assert mark_phase.call_args.kwargs["status"] == "failed"


def test_monitor_reader_rollback_preserves_a_foreign_listener(runtime, tmp_path, monkeypatch):
    project, proc, _properties, listeners, _http = runtime
    (proc / "12/cgroup").write_text("0::/foreign.service\n")
    monkeypatch.setattr(service, "_restore_previous_units", lambda *_: True)
    monkeypatch.setattr(service_release, "previous_source_root", lambda _: tmp_path / "previous")
    monkeypatch.setattr(service_ops, "service_exists", lambda _: True)
    monkeypatch.setattr(service_ops, "_service_main_pid", lambda _: 11)
    monkeypatch.setattr(service_ops, "_port_open", lambda _: True)
    monkeypatch.setattr(service_ops, "sync_systemd_units", lambda _: 0)
    run = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "run", run)
    assert service._rollback_monitor_and_reader(project, project, Mock(), True) is False
    run.assert_not_called()
    assert all(call.args[0][0] == "ss" for call in listeners.call_args_list)


@pytest.fixture
def lifecycle(monkeypatch, project):
    monkeypatch.setattr(service, "_load", lambda _: project)
    calls = {}
    for name in ("ensure_infra", "sync_backend", "build_frontend", "run_migrations",
                 "sync_systemd_units", "restart_service", "verify_health", "sync_seeds"):
        calls[name] = Mock(return_value=0)
        monkeypatch.setattr(service_ops, name, calls[name])
    monkeypatch.setattr(service_ops, "service_state", lambda name: "inactive" if name == "stopped.service" else "active")
    monkeypatch.setattr(service_ops, "service_exists", lambda _: True)
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
    assert all(call.kwargs.get("project") is not None for call in lifecycle["restart_service"].call_args_list)


def test_rebuild_ignores_other_sessions_and_tasks(lifecycle, monkeypatch):
    """A rebuild deploys committed, accepted source, so the pulse's session and
    task state cannot change what ships and never blocks it."""
    from cli.commands import pulse

    monkeypatch.setattr(pulse, "fetch_pulse_payload", Mock(side_effect=AssertionError("rebuild read the pulse")))
    result = CliRunner().invoke(service.app, ["rebuild", "example"])
    assert result.exit_code == 0, result.output


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


def test_release_installs_clone_from_a_cache_beside_the_release(project, monkeypatch, tmp_path):
    state = tmp_path.resolve() / "state"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", "state")  # relative: options must still be absolute
    source = state / "projects" / "example" / "releases" / ("a" * 32) / "source"
    release = replace(project, root=source, backend_dir=source / "backend", frontend_dir=source / "frontend")
    release.backend_dir.mkdir(parents=True)
    (release.backend_dir / "pyproject.toml").write_text("[project]\nname='x'\n")
    (release.backend_dir / "uv.lock").touch()
    release.frontend_dir.mkdir()
    (release.frontend_dir / "package.json").write_text("{}")
    def run_command(command, **_kwargs):
        # An install holds the release caches, so host retention's prune skips it; a build does not.
        with service_release.release_cache_lock(exclusive=True) as prune_admitted:
            assert prune_admitted is (tuple(command[:2]) not in {("uv", "sync"), ("pnpm", "install")})
        return 0

    run = Mock(side_effect=run_command)
    monkeypatch.setattr(service_ops, "run", run)

    assert service_ops.sync_backend(release) == 0
    assert run.call_args.args[0] == ["uv", "sync", "--locked", "--cache-dir", str(state / "cache" / "uv"),
                                     "--link-mode", "clone"]
    assert service_ops.build_frontend(release) == 0
    pnpm_install = [
        "pnpm", "install", "--frozen-lockfile", "--store-dir", str(state / "cache" / "pnpm-store"),
        "--package-import-method", "clone-or-copy", "--config.confirm-modules-purge=false"]
    assert run.call_args_list[1].args[0] == pnpm_install
    assert run.call_args_list[-1].args[0] == ["pnpm", "build"]
    # The private deploy clone also lives under the state root.
    clone = state / "projects" / "example" / "source"
    shutil.copytree(source, clone)
    run.reset_mock()
    assert service_ops.install_clone_dependencies(replace(project, source_repo=clone)) == 0
    assert run.call_args.args[0] == pnpm_install and run.call_args.kwargs["cwd"] == clone / "frontend"
    (release.frontend_dir / "package-lock.json").touch()
    npm = service_ops.frontend_install_plan(release.frontend_dir, source)
    assert npm is not None and service_ops.release_cache_options(npm.manager, source) == []
    # A checkout outside the state root keeps the user's own caches.
    assert service_ops.release_cache_options("uv", tmp_path / "checkout") == []


def _probe_infra(monkeypatch, *, pg_ok: bool, hatchet_status: int | None):
    def capture(command, **_kwargs):
        assert command[0] == "pg_isready"
        return subprocess.CompletedProcess(command, 0 if pg_ok else 2, "", "")

    def get(*_args, **_kwargs):
        if hatchet_status is None:
            raise service_ops.httpx.ConnectError("down")
        return SimpleNamespace(status_code=hatchet_status)

    run = Mock()
    monkeypatch.setattr(service_ops, "capture", capture)
    monkeypatch.setattr(service_ops, "run", run)
    monkeypatch.setattr(service_ops.httpx, "get", get)
    _infra_status_api(monkeypatch, [
        {"service": name, "state": "running" if up else "stopped", "health": "healthy" if up else ""}
        for name, up in (("postgres", pg_ok), ("hatchet", hatchet_status is not None and hatchet_status < 400))
    ])
    return run


def _infra_status_api(monkeypatch, rows):
    client = Mock()
    client._global_url.return_value = "/docker/status"
    client.get.return_value = rows
    factory = Mock(return_value=nullcontext(client))
    monkeypatch.setattr(service_ops, "STClient", factory, raising=False)
    return client, factory


def test_infrastructure_uses_reachable_status_when_direct_probes_are_blocked(project, monkeypatch, capsys):
    run = _probe_infra(monkeypatch, pg_ok=False, hatchet_status=None)
    client, _ = _infra_status_api(monkeypatch, [
        {"service": name, "state": "running", "health": "healthy"} for name in ("postgres", "hatchet")
    ])

    assert service_ops.ensure_infra(project) == 0
    client.get.assert_called_once_with("/docker/status")
    assert "restart" not in capsys.readouterr().out
    run.assert_not_called()


@pytest.mark.parametrize("pg_code,hatchet_status,down", [(0, 503, "hatchet"), (1, 200, "postgres")])
def test_infrastructure_readiness_failure_is_not_overridden_by_open_ports(
    project, monkeypatch, capsys, pg_code, hatchet_status, down,
):
    _probe_infra(monkeypatch, pg_ok=True, hatchet_status=hatchet_status)
    monkeypatch.setattr(service_ops, "capture", lambda command: subprocess.CompletedProcess(command, pg_code, "", ""))
    _, factory = _infra_status_api(monkeypatch, [
        {"service": name, "state": "running", "health": "healthy"} for name in ("postgres", "hatchet")
    ])

    assert service_ops.ensure_infra(project) == 1
    out = capsys.readouterr().out
    assert f"infrastructure is down ({down})" in out
    assert service_ops.INFRA_RESTART_HINT in out
    factory.assert_not_called()


def test_infrastructure_probe_configuration_error_is_not_service_downtime(project, monkeypatch, capsys):
    _probe_infra(monkeypatch, pg_ok=True, hatchet_status=200)
    monkeypatch.setattr(service_ops, "capture", lambda command: subprocess.CompletedProcess(command, 3, "", ""))
    _, factory = _infra_status_api(monkeypatch, [{"service": "postgres", "state": "running", "health": "healthy"}])

    assert service_ops.ensure_infra(project) == 1
    out = capsys.readouterr().out
    assert "pg_isready exited 3" in out
    assert "status unavailable" in out
    assert "unit.restart" not in out
    factory.assert_not_called()


def test_infrastructure_is_a_port_probe_that_never_starts_anything(project, monkeypatch):
    run = _probe_infra(monkeypatch, pg_ok=True, hatchet_status=200)

    assert service_ops.ensure_infra(project) == 0
    run.assert_not_called()


def test_infrastructure_down_points_at_the_nightshift_restart(project, monkeypatch, capsys):
    run = _probe_infra(monkeypatch, pg_ok=True, hatchet_status=None)

    assert service_ops.ensure_infra(project) == 1
    out = capsys.readouterr().out
    assert "hatchet" in out
    assert "postgres" not in out
    assert "nightshift request unit.restart unit=summitflow-stack.service" in out
    run.assert_not_called()


@pytest.mark.parametrize("rows", [
    [], None, {}, [{"service": "hatchet", "state": "unknown", "health": ""}],
    [{"service": "hatchet", "state": "running", "health": ""}],
])
def test_infrastructure_unknown_does_not_recommend_restart(project, monkeypatch, capsys, rows):
    _probe_infra(monkeypatch, pg_ok=True, hatchet_status=None)
    _infra_status_api(monkeypatch, rows)

    assert service_ops.ensure_infra(project) == 1
    out = capsys.readouterr().out
    assert "status unavailable" in out
    assert "infrastructure is down" not in out
    assert "unit.restart" not in out


@pytest.mark.parametrize("error", [
    service_ops.httpx.ConnectError("blocked"), service_ops.httpx.ReadTimeout("timeout"),
    service_ops.APIError(503, "unavailable"), ValueError("invalid JSON"),
])
def test_infrastructure_api_unreachable_does_not_recommend_restart(project, monkeypatch, capsys, error):
    _probe_infra(monkeypatch, pg_ok=True, hatchet_status=None)
    client, _ = _infra_status_api(monkeypatch, [])
    client.get.side_effect = error

    assert service_ops.ensure_infra(project) == 1
    out = capsys.readouterr().out
    assert "status unavailable" in out
    assert "unit.restart" not in out


def test_infrastructure_reports_authoritative_unhealthy_status(project, monkeypatch, capsys):
    _probe_infra(monkeypatch, pg_ok=True, hatchet_status=None)
    _infra_status_api(monkeypatch, [{"service": "hatchet", "state": "running", "health": "unhealthy"}])

    assert service_ops.ensure_infra(project) == 1
    assert service_ops.INFRA_RESTART_HINT in capsys.readouterr().out


def test_infrastructure_direct_success_and_empty_declaration_skip_api(project, monkeypatch):
    _probe_infra(monkeypatch, pg_ok=True, hatchet_status=200)
    _, factory = _infra_status_api(monkeypatch, [])
    assert service_ops.ensure_infra(project) == 0
    assert service_ops.ensure_infra(replace(project, infra=())) == 0
    factory.assert_not_called()


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


@pytest.mark.parametrize("runtime_user", ["", "owner"])
def test_migrations_load_registered_home_credentials_without_shell_secrets(project, monkeypatch, tmp_path,
                                                                          runtime_user):
    home = tmp_path / "home"
    credentials = home / ".config" / "credstore" / "jobinator-4000" / "env"
    credentials.parent.mkdir(parents=True)
    credentials.write_text(
        "JOBINATOR_DB_URL=postgresql://registered-fixture\n"
        "PORTFOLIO_DB_URL=postgresql://other-project\n"
        "INTERNAL_SERVICE_SECRET=unrelated-fixture\n"
    )
    monkeypatch.setattr(service_ops.Path, "home", lambda: home)
    monkeypatch.delenv("JOBINATOR_DB_URL", raising=False)
    monkeypatch.setenv("PORTFOLIO_DB_URL", "postgresql://shell-fixture")
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "shell-fixture")
    backend = tmp_path / "accepted" / "backend"
    executable = backend / ".venv" / "bin" / "alembic"
    executable.parent.mkdir(parents=True)
    (backend / "alembic.ini").touch()
    executable.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "if not os.environ.get('JOBINATOR_DB_URL'):\n"
        "    raise RuntimeError('JOBINATOR_DB_URL is not configured')\n"
        "assert os.environ['JOBINATOR_DB_URL'] == 'postgresql://registered-fixture'\n"
        "assert 'PORTFOLIO_DB_URL' not in os.environ\n"
        "assert 'INTERNAL_SERVICE_SECRET' not in os.environ\n"
    )
    executable.chmod(0o700)
    deployed = replace(project, project_id="jobinator-4000", root=backend.parent, backend_dir=backend,
                       host_config_root=tmp_path / "host", runtime_user=runtime_user)

    assert service_ops.run_migrations(deployed) == 0


@pytest.mark.parametrize("project_id, wanted, other, files", [
    # Host .env.local beats host .env, the accepted source's .env and the shell.
    ("portfolio-ai", "PORTFOLIO_DB_URL", "JOBINATOR_DB_URL", {
        "source/.env": "PORTFOLIO_DB_URL=postgresql://source-stale\n",
        "host/.env": "PORTFOLIO_DB_URL=postgresql://host-base\n",
        "host/.env.local": "PORTFOLIO_DB_URL=postgresql://approved\n"}),
    ("learn-o-tron", "LEARN_DB_URL", "PORTFOLIO_DB_URL", {"host/backend/.env": "LEARN_DB_URL=postgresql://approved\n"}),
    ("jobinator-4000", "JOBINATOR_DB_URL", "PORTFOLIO_DB_URL", {"home/.env.local": "JOBINATOR_DB_URL=postgresql://approved\n"}),
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
        extra = (f"{other}=postgresql://other-project\nINTERNAL_SERVICE_SECRET=not-for-migrations\n"
                 "PROXMOX_TOKEN_SECRET=pve-secret\n")
        path.write_text(content + ("" if "stale" in content or "base" in content else extra))
    (tmp_path / "home").mkdir(exist_ok=True)
    monkeypatch.setattr(service_ops.Path, "home", lambda: tmp_path / "home")
    if project_id == "portfolio-ai":
        monkeypatch.setenv(wanted, "postgresql://stale-shell")
        monkeypatch.setenv("DATABASE_URL", "postgresql://other-project")
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET", raising=False)
    # Neither an unclaimed internal/PVE secret nor another project's database
    # key in the operator shell reaches the migration.
    monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "pve-secret")
    monkeypatch.setenv("OMINULL_INTERNAL_TOKEN", "unclaimed-internal")
    monkeypatch.setenv(other, "postgresql://other-project-shell")
    run = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "run", run)
    deployed = replace(project, project_id=project_id, root=accepted_root, backend_dir=backend_dir,
                       frontend_dir=accepted_root / "frontend", host_config_root=tmp_path / "host")

    assert service_ops.run_migrations(deployed) == 0
    migration_env = run.call_args.kwargs["env"]
    assert migration_env[wanted] == "postgresql://approved"
    assert not {other, "DATABASE_URL", "INTERNAL_SERVICE_SECRET", "PROXMOX_TOKEN_SECRET",
                "OMINULL_INTERNAL_TOKEN"} & migration_env.keys()
    assert "PATH" in migration_env
    assert run.call_args.kwargs["cwd"] == backend_dir


def test_unlisted_project_migrations_get_only_database_url_from_own_env(project, monkeypatch, tmp_path):
    backend_dir = tmp_path / "source" / "backend"
    (backend_dir / ".venv" / "bin").mkdir(parents=True)
    (backend_dir / "alembic.ini").touch()
    (backend_dir / ".venv" / "bin" / "alembic").touch()
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / ".env.local").write_text("DATABASE_URL=postgresql://shared\nPROXMOX_TOKEN_SECRET=pve\n")
    (tmp_path / "host").mkdir()
    (tmp_path / "host" / ".env.local").write_text(
        "DATABASE_URL=postgresql://own\nAGENT_HUB_DB_URL=postgresql://other\nPROXMOX_TOKEN_SECRET=pve\n")
    monkeypatch.setattr(service_ops.Path, "home", lambda: tmp_path / "home")
    run = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "run", run)
    deployed = replace(project, project_id="unlisted-project", root=tmp_path / "source", backend_dir=backend_dir,
                       frontend_dir=tmp_path / "source" / "frontend", host_config_root=tmp_path / "host")

    assert service_ops.run_migrations(deployed) == 0
    migration_env = run.call_args.kwargs["env"]
    assert migration_env["DATABASE_URL"] == "postgresql://own"
    assert not {"AGENT_HUB_DB_URL", "PROXMOX_TOKEN_SECRET"} & migration_env.keys()


def test_migration_table_refuses_a_key_granted_to_two_projects(tmp_path):
    from cli.lib import migration_env

    table = tmp_path / "migration-env.json"
    table.write_text(json.dumps({"projects": {
        "a": {"database_key": "A_DB_URL", "keys": ["A_DB_URL"], "sources": ["project"]},
        "b": {"database_key": "B_DB_URL", "keys": ["B_DB_URL", "A_DB_URL"], "sources": ["project"]},
    }}))
    with pytest.raises(ValueError, match="A_DB_URL is granted to both a and b"):
        migration_env._load(table)
    table.write_text(json.dumps({"projects": {
        "a": {"database_key": "A_DB_URL", "keys": ["A_DB_URL"], "sources": ["anywhere"]}}}))
    with pytest.raises(ValueError, match="invalid migration grant"):
        migration_env._load(table)


def test_committed_migration_table_loads():
    from cli.lib import migration_env

    assert migration_env.grant_for("agent-hub").database_key == "AGENT_HUB_DB_URL"
    assert migration_env.grant_for("jobinator-4000").sources == ("shared", "project")
    assert {"PORTFOLIO_SECRET_KEY", "LEARN_DB_URL", "INTERNAL_SERVICE_SECRET"} <= migration_env.strip_keys()


def test_portfolio_migrations_get_their_secret_key_from_host_env(project, monkeypatch, tmp_path):
    backend_dir = tmp_path / "source" / "backend"
    (backend_dir / ".venv" / "bin").mkdir(parents=True)
    (backend_dir / "alembic.ini").touch()
    (backend_dir / ".venv" / "bin" / "alembic").touch()
    (tmp_path / "host").mkdir()
    (tmp_path / "host" / ".env.local").write_text("PORTFOLIO_SECRET_KEY=approved-key\n")
    monkeypatch.setenv("PORTFOLIO_SECRET_KEY", "stale-shell-key")
    # A workstation's real credential store must never override this fixture.
    monkeypatch.setattr(service_ops, "credstore_root", lambda _: tmp_path / "credstore")
    run = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "run", run)

    for project_id, expected in (("portfolio-ai", "approved-key"), ("jobinator-4000", None)):
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
    assert "frontend.service" in [call.args[0] for call in lifecycle["restart_service"].call_args_list]


def test_cli_runtime_backend_scope_does_not_restart_the_only_frontend(project, lifecycle, monkeypatch):
    monkeypatch.setattr(service, "_load", lambda _: replace(
        project, backend_service="", backend_dir=project.root, frontend_dir=project.root,
    ))
    result = CliRunner().invoke(service.app, ["rebuild", "example", "--scope", "backend"])
    assert result.exit_code == 0, result.output
    restarted = [call.args[0] for call in lifecycle["restart_service"].call_args_list]
    assert restarted == ["required.service", "active.service"]
    assert "shared component directory; using full rebuild" not in result.output
    checked = lifecycle["verify_health"].call_args.args[0]
    assert not checked.frontend_service


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
    monkeypatch.setattr(service_ops, "service_exists", lambda _: True)
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
    lifecycle["sync_systemd_units"].side_effect = lambda _p, **_k: order.append("units") or 0
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


def test_infrastructure_checks_only_what_the_project_declares(project, monkeypatch):
    run = _probe_infra(monkeypatch, pg_ok=False, hatchet_status=None)

    assert service_ops.ensure_infra(replace(project, infra=())) == 0
    assert service_ops.ensure_infra(replace(project, infra=("hatchet",))) == 1
    run.assert_not_called()


MANUAL = "daemon@default.service"


@pytest.fixture
def manual_lifecycle(lifecycle, project, monkeypatch):
    managed = replace(project, manual_workers=(MANUAL,))
    monkeypatch.setattr(service, "_load", lambda _: managed)
    monkeypatch.setattr(service_ops, "manual_worker_release_references", Mock(return_value=set()))
    monkeypatch.setattr(service_ops, "changed_manual_workers", Mock(return_value=()))
    return lifecycle


def _restarted(calls) -> list[str]:
    return [call.args[0] for call in calls["restart_service"].call_args_list]


def test_identity_accepts_manual_workers_but_not_a_unit_in_two_roles(tmp_path):
    identity = {"project": {"id": "example"}, "runtime": {},
                "services": {"backend": "web.service", "manual_workers": [MANUAL]}}
    parsed = service_ops._project_from_identity(identity, "example", tmp_path)
    assert parsed.manual_workers == (MANUAL,)
    assert MANUAL not in parsed.all_services
    assert MANUAL not in parsed.workers(include_all=True)
    identity["services"]["optional_workers"] = ["daemon@default"]
    with pytest.raises(service_ops.ServiceError, match="manual_workers"):
        service_ops._project_from_identity(identity, "example", tmp_path)


@pytest.mark.parametrize("args", [[], ["--scope", "backend"], ["--scope", "worker"]])
def test_normal_rebuild_leaves_an_unchanged_manual_worker_alone(manual_lifecycle, project, monkeypatch, args):
    # Overlapping component dirs force full scope; the manual worker still stays out.
    monkeypatch.setattr(service, "_load", lambda _: replace(
        project, frontend_dir=project.root, backend_dir=project.root, manual_workers=(MANUAL,)))
    result = CliRunner().invoke(service.app, ["rebuild", "example", *args])
    assert result.exit_code == 0, result.output
    assert MANUAL not in _restarted(manual_lifecycle)
    assert "backend.service" in _restarted(manual_lifecycle)
    assert manual_lifecycle["sync_systemd_units"].call_args.kwargs == {"manual": ()}
    assert "leaving manual workers unchanged (stopped, or no change since their release): " + MANUAL in result.output


def test_one_rebuild_also_deploys_a_manual_worker_whose_source_changed(manual_lifecycle, monkeypatch):
    changed = Mock(return_value=(MANUAL,))
    monkeypatch.setattr(service_ops, "changed_manual_workers", changed)
    result = CliRunner().invoke(service.app, ["rebuild", "example"])
    assert result.exit_code == 0, result.output
    assert changed.call_args.args[2] == "c" * 40  # the release's commit
    assert changed.call_args.kwargs["repo"] == service._load("example").git_root  # the checkout, not the release
    assert "changed since their running release, so also restarting: " + MANUAL in result.output
    assert _restarted(manual_lifecycle)[0] == "backend.service" and MANUAL in _restarted(manual_lifecycle)
    renders = [call.kwargs for call in manual_lifecycle["sync_systemd_units"].call_args_list]
    assert renders == [{"manual": ()}, {"manual": (MANUAL,)}]
    assert ("manual_worker_units", "succeeded") in _phases()
    assert MANUAL in _mock(service_release.mark_phase).call_args_list[0].kwargs["workers"]
    manual_lifecycle["verify_health"].assert_called_once()


@pytest.mark.parametrize("args", [["--scope", "backend"], ["--scope", "frontend"]])
def test_a_narrowed_rebuild_never_deploys_a_manual_worker(manual_lifecycle, monkeypatch, args):
    changed = Mock(return_value=(MANUAL,))
    monkeypatch.setattr(service_ops, "changed_manual_workers", changed)
    assert CliRunner().invoke(service.app, ["rebuild", "example", *args]).exit_code == 0
    changed.assert_not_called()
    assert MANUAL not in _restarted(manual_lifecycle)


def test_a_failed_rebuild_restores_the_manual_worker_it_rendered(manual_lifecycle, monkeypatch, tmp_path):
    previous = tmp_path / "previous" / "source"
    monkeypatch.setattr(service_release, "previous_source_root", lambda _release: previous)
    monkeypatch.setattr(service_ops, "changed_manual_workers", Mock(return_value=(MANUAL,)))
    monkeypatch.setattr(service_ops, "service_state", lambda _: "failed")
    assert CliRunner().invoke(service.app, ["rebuild", "example"]).exit_code == 1
    restores = [call for call in manual_lifecycle["sync_systemd_units"].call_args_list if call.args[0].root == previous]
    assert [call.kwargs for call in restores] == [{"manual": ()}, {"manual": (MANUAL,)}]


def test_a_manual_worker_changed_when_its_unit_or_working_directory_did(project, monkeypatch, tmp_path, capsys):
    import subprocess

    repo = project.root
    git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
    git("init", "-q")
    git("config", "user.email", "t@example.test")
    git("config", "user.name", "t")
    (repo / "scripts" / "systemd").mkdir(parents=True, exist_ok=True)
    (repo / "scripts" / "systemd" / MANUAL).write_text("[Service]\nWorkingDirectory=__PROJECT_ROOT__/daemon\n")
    (repo / "daemon").mkdir()
    (repo / "daemon" / "main.ts").write_text("1")
    (repo / "web.ts").write_text("1")

    def commit(path: str) -> str:
        (repo / path).write_text((repo / path).read_text() + "+")
        git("add", "-A")
        git("commit", "-qm", path)
        return git("rev-parse", "HEAD")

    git("add", "-A")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    elsewhere = commit("web.ts")
    daemon = commit("daemon/main.ts")
    unit = commit(f"scripts/systemd/{MANUAL}")
    releases = tmp_path / "state" / "projects" / "example" / "releases"
    (releases / ("a" * 32) / "source" / "daemon").mkdir(parents=True)
    proc = tmp_path / "proc" / "41"
    proc.mkdir(parents=True)
    (proc / "cwd").symlink_to(releases / ("a" * 32) / "source" / "daemon", target_is_directory=True)
    monkeypatch.setattr(service_ops, "_PROC_ROOT", tmp_path / "proc")
    pids = {MANUAL: 41}
    monkeypatch.setattr(service_ops, "_service_main_pid", lambda name: pids.get(name, 0))
    running = {"commit": base}
    monkeypatch.setattr(service_release, "build_commit",
                        lambda project_id, build_id, state_root: running["commit"]
                        if (project_id, build_id, state_root) == ("example", "a" * 32, tmp_path / "state") else None)
    # The rebuild hands over the release's project, whose root is a git archive extraction with no .git;
    # the diff runs in the checkout.
    source = releases / ("a" * 32) / "source"
    (source / "scripts" / "systemd").mkdir(parents=True)
    (source / "scripts" / "systemd" / MANUAL).write_text((repo / "scripts" / "systemd" / MANUAL).read_text())
    managed = replace(project, root=source, manual_workers=(MANUAL, "stopped@default.service"))
    changed = lambda new: service_ops.changed_manual_workers(managed, releases, new, repo=repo)  # noqa: E731
    assert changed(base) == ()
    assert changed(elsewhere) == ()
    assert changed(daemon) == (MANUAL,)
    running["commit"] = daemon
    assert changed(unit) == (MANUAL,)
    running["commit"] = None  # its release cannot be read
    assert changed(elsewhere) == (MANUAL,)
    running["commit"] = "f" * 40  # git cannot compare it: restart, and say why
    assert changed(elsewhere) == (MANUAL,)
    assert f"could not compare {MANUAL}'s release ffffffffffff" in capsys.readouterr().out
    pids.clear()  # stopped: nothing to restart
    assert changed(unit) == ()


def test_named_manual_worker_rebuilds_only_its_unit(manual_lifecycle, project, monkeypatch):
    monkeypatch.setattr(service, "_load", lambda _: replace(
        project, frontend_dir=project.root, backend_dir=project.root, manual_workers=(MANUAL,)))
    result = CliRunner().invoke(service.app, ["rebuild", "example", "--worker", "daemon@default"])
    assert result.exit_code == 0, result.output
    assert _restarted(manual_lifecycle) == [MANUAL]
    assert manual_lifecycle["sync_systemd_units"].call_args.kwargs == {"manual": (MANUAL,)}
    for skipped in ("run_migrations", "verify_health", "sync_seeds"):
        manual_lifecycle[skipped].assert_not_called()
    assert "using full rebuild" not in result.output
    assert _phases() == [
        ("deployment_scope", "selected"), ("migrations", "not_applicable"),
        ("infrastructure", "succeeded"), ("backend_dependencies", "succeeded"),
        ("frontend_build", "succeeded"), ("systemd_units", "succeeded"), ("restart", "succeeded"),
        ("health", "succeeded"), ("seeds", "not_applicable"),
    ]
    assert _mock(service_release.mark_phase).call_args_list[0].kwargs["scope"] == "manual"
    _mock(service_release.complete_release).assert_called_once()


@pytest.mark.parametrize("extra", [["--worker", "required.service"], ["--include-all-workers"],
                                   ["--scope", "worker"]])
def test_manual_worker_rebuild_refuses_other_selection(manual_lifecycle, extra):
    result = CliRunner().invoke(service.app, ["rebuild", "example", "--worker", MANUAL, *extra])
    assert result.exit_code == 1
    assert "manual worker rebuilds alone" in result.output
    manual_lifecycle["ensure_infra"].assert_not_called()


def test_failed_manual_worker_restores_only_its_unit(manual_lifecycle, monkeypatch, tmp_path):
    previous = tmp_path / "previous" / "source"
    monkeypatch.setattr(service_release, "previous_source_root", lambda _release: previous)
    monkeypatch.setattr(service_ops, "service_state", lambda _: "failed")
    result = CliRunner().invoke(service.app, ["rebuild", "example", "--worker", MANUAL])
    assert result.exit_code == 1, result.output
    restore = manual_lifecycle["sync_systemd_units"].call_args
    assert restore.args[0].root == previous
    assert restore.kwargs == {"manual": (MANUAL,)}


def test_release_cleanup_keeps_the_release_a_manual_worker_runs_from(manual_lifecycle, monkeypatch):
    old = Path("/releases") / ("a" * 32)
    monkeypatch.setattr(service_ops, "release_references_for_services", Mock(return_value={Path("/releases/x")}))
    monkeypatch.setattr(service_ops, "manual_worker_release_references", Mock(return_value={old}))
    assert CliRunner().invoke(service.app, ["rebuild", "example"]).exit_code == 0
    references = _mock(service_release.complete_release).call_args.kwargs["service_references"]
    assert references == {Path("/releases/x"), old}
    monkeypatch.setattr(service_ops, "manual_worker_release_references", Mock(return_value=None))
    assert CliRunner().invoke(service.app, ["rebuild", "example"]).exit_code == 0
    assert _mock(service_release.complete_release).call_args.kwargs["service_references"] is None


def test_manual_worker_release_reference_reads_the_running_process(project, monkeypatch, tmp_path):
    releases = tmp_path / "releases"
    source = releases / ("a" * 32) / "source"
    source.mkdir(parents=True)
    proc = tmp_path / "proc" / "41"
    proc.mkdir(parents=True)
    (proc / "cwd").symlink_to(source, target_is_directory=True)
    monkeypatch.setattr(service_ops, "_PROC_ROOT", tmp_path / "proc")
    monkeypatch.setattr(service_ops, "_service_main_pid", lambda unit: 41 if unit == MANUAL else 0)
    managed = replace(project, manual_workers=(MANUAL, "idle.service"))
    assert service_ops.manual_worker_release_references(managed, releases) == {releases / ("a" * 32)}
    (proc / "cwd").unlink()
    assert service_ops.manual_worker_release_references(managed, releases) is None
    assert service_ops.manual_worker_release_references(project, tmp_path / "missing") == set()


def test_unit_sync_start_and_stop_leave_manual_workers_alone(project, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    managed = replace(project, backend_service="web.service", frontend_service="", default_workers=(),
                      optional_workers=(), manual_workers=(MANUAL,))
    templates = managed.root / "scripts" / "systemd"
    templates.mkdir(parents=True)
    for name in ("web.service", MANUAL):
        (templates / name).write_text("WorkingDirectory=__PROJECT_ROOT__\n[Install]\n")
    commands: list[list[str]] = []
    monkeypatch.setattr(service_ops, "run", lambda command, **_: commands.append(command[2:]) or 0)
    units = tmp_path / "config" / "systemd" / "user"
    assert service_ops.sync_systemd_units(managed) == 0
    assert [path.name for path in units.iterdir()] == ["web.service"]
    assert commands[-1] == ["enable", "web.service"]
    assert service_ops.sync_systemd_units(managed, manual=(MANUAL,)) == 0
    assert sorted(path.name for path in units.iterdir()) == [MANUAL, "web.service"]
    assert commands[-1] == ["enable", MANUAL]
    commands.clear()
    monkeypatch.setattr(service_ops.service_release, "current_source_root", lambda _: None)
    monkeypatch.setattr(service_ops, "service_exists", lambda _: True)
    assert service_ops.start_services(managed) == 0
    assert service_ops.stop_services(managed) == 0
    assert not any(MANUAL in command for command in commands)


def test_status_lists_manual_workers_read_only(manual_lifecycle, monkeypatch):
    monkeypatch.setattr(service_ops, "service_state",
                        lambda name: "inactive" if name in {"stopped.service", MANUAL} else "active")
    result = CliRunner().invoke(service.app, ["status", "example"])
    assert result.exit_code == 0, result.output
    assert f"manual: {MANUAL}:inactive" in result.output


def test_host_monitor_build_reuses_live_crates_but_recompiles_the_collector(project, monkeypatch, tmp_path):
    release = tmp_path / "new" / "source"
    (release / "host-monitor").mkdir(parents=True)
    (release / "host-monitor" / "Cargo.toml").write_text('[package]\nname = "summitflow-host-monitor"\n')
    (release / "host-monitor" / "Cargo.lock").write_text("")
    live = tmp_path / "live" / "source"
    (live / "host-monitor" / "target" / "release" / "deps").mkdir(parents=True)
    (live / "host-monitor" / "target" / "release" / "deps" / "libdep.rlib").write_text("compiled")
    monkeypatch.setattr(service_release, "current_source_root", lambda _project_id: live)
    commands: list[list[str]] = []
    monkeypatch.setattr(service_ops, "run", lambda command, **_kwargs: commands.append(command) or 0)
    monkeypatch.setattr(service_ops.host_monitor_deploy, "build_helper", lambda _root: None)
    monitor = replace(project, project_id="summitflow", root=release,
                      default_workers=("summitflow-host-monitor.service",))

    assert service_ops.build_host_monitor(monitor) == 0

    assert (release / "host-monitor" / "target" / "release" / "deps" / "libdep.rlib").read_text() == "compiled"
    assert [command[1:] for command in commands] == [
        ["clean", "--release", "-p", "summitflow-host-monitor"],
        ["build", "--locked", "--release"],
    ]


def test_frontend_build_seeds_the_next_cache_from_the_live_release(project, monkeypatch, tmp_path):
    release = tmp_path / "new" / "source"
    live = tmp_path / "live" / "source"
    (live / "frontend" / ".next" / "cache" / "webpack").mkdir(parents=True)
    (live / "frontend" / ".next" / "cache" / "webpack" / "pack").write_text("cached")
    monkeypatch.setattr(service_release, "current_source_root", lambda _project_id: live)
    monkeypatch.setattr(service_ops, "frontend_install_plan", lambda *_args: service_ops.FrontendInstall(
        "npm", ("npm", "ci"), release / "frontend"))
    monkeypatch.setattr(service_ops, "run", lambda _command, **_kwargs: 0)
    frontend = replace(project, root=release, frontend_dir=release / "frontend")

    assert service_ops.build_frontend(frontend) == 0

    assert (release / "frontend" / ".next" / "cache" / "webpack" / "pack").read_text() == "cached"
