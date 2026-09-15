"""Fixed runner deployment: real filesystem transactions, simulated guest services."""

import base64
import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from cli.commands import service
from cli.lib import neri_runner_deploy as deploy
from cli.lib import neri_runner_guest as guest
from cli.lib import service_ops
from cli.lib.proxmox import ProxmoxError

ATTEMPT = "1" * 32


def payload(files):
    return {"identity": guest.identity(files), "files": {
        name: base64.b64encode(value).decode() for name, value in files.items()
    }}


@pytest.fixture
def installed(tmp_path, monkeypatch):
    root = tmp_path / "guest"
    root.mkdir()
    monkeypatch.setattr(guest, "ROOT", root)
    monkeypatch.setattr(guest, "PRIVILEGED_UID", os.getuid())
    files = {name: b"old-" + name.encode() for name in guest.FILES}
    for name, contents in files.items():
        (root / name).write_bytes(contents)
    state: dict[str, Any] = {"release": guest.identity(files), "busy": False, "protocol": guest.ADAPTER, "calls": []}

    def health(config, port):
        return {
            "status": "ok", "failure": None, "stopped": not state["busy"], "busy": state["busy"],
            "release": state["release"], "deployment_protocol": state["protocol"],
            "deployment_blocked": (root / ".deploying").exists(),
        }

    def systemctl(action):
        state["calls"].append(action)
        if action == "restart":
            state["release"] = guest.read_identity(root)
            state["protocol"] = guest.ADAPTER

    monkeypatch.setattr(guest, "profile_health", health)
    monkeypatch.setattr(guest, "systemctl", systemctl)
    return root, files, state


def new_bundle():
    return payload({name: b"new-" + name.encode() for name in guest.FILES})


def test_success_preserves_old_bundle_and_atomically_selects_new(installed):
    root, old, state = installed
    result = guest.deploy(ATTEMPT, new_bundle())
    assert result["state"] == "succeeded", result
    assert result["after"]["installed"] == new_bundle()["identity"]
    assert guest.read_identity(root / "previous") == guest.identity(old)
    assert (root / "current").is_symlink()
    assert all((root / name).is_symlink() for name in guest.FILES)
    assert state["calls"] == ["stop", "restart"]
    assert not (root / ".deploying").exists()
    assert json.loads((root / "deployments" / (ATTEMPT + ".json")).read_text()) == result
    assert [event["phase"] for event in result["events"]] == [
        "inspect", "interlock", "stage", "activate", "restart", "verify", "verified",
    ]


def test_release_is_readable_with_restrictive_guest_umask(installed):
    root, _old, _state = installed
    previous_umask = os.umask(0o077)
    try:
        result = guest.deploy(ATTEMPT, new_bundle())
    finally:
        os.umask(previous_umask)
    assert result["state"] == "succeeded"
    assert (root / "releases").stat().st_mode & 0o777 == 0o755
    assert (root / "current").stat().st_mode & 0o777 == 0o755
    assert (root / "current" / "proxy_core.py").stat().st_mode & 0o777 == 0o644


def test_equal_digest_requires_running_identity_and_is_noop(installed):
    root, old, state = installed
    result = guest.deploy(ATTEMPT, payload(old))
    assert result["state"] == "noop"
    assert state["calls"] == []
    assert not (root / "releases").exists()
    state["release"] = new_bundle()["identity"]
    result = guest.deploy("2" * 32, payload(old))
    assert result["state"] == "failed"
    assert "Running release identity" in result["error"]
    assert state["calls"] == []


def test_unknown_prior_running_identity_refuses_a_new_release(installed):
    root, old, state = installed
    state["release"] = {"release_id": "unknown"}
    result = guest.deploy(ATTEMPT, new_bundle())
    assert result["state"] == "failed"
    assert "Running release identity" in result["error"]
    assert guest.read_identity(root) == guest.identity(old)
    assert not (root / ".deploying").exists()
    assert not state["calls"]
    assert not (root / "releases").exists()


@pytest.mark.parametrize("profile", [0, 1])
def test_either_busy_profile_refuses_before_staging(installed, monkeypatch, profile):
    root, old, state = installed
    health = guest.profile_health

    def busy_health(config, port):
        result = health(config, port)
        if port == guest.PROFILES[profile][2]:
            result["busy"] = True
        return result

    monkeypatch.setattr(guest, "profile_health", busy_health)
    result = guest.deploy(ATTEMPT, new_bundle())
    assert result["state"] == "failed"
    assert "busy" in result["error"]
    assert guest.read_identity(root) == guest.identity(old)
    assert not (root / "releases").exists()
    assert not (root / ".deploying").exists()
    assert not state["calls"]


def test_second_idle_check_closes_permit_race(installed, monkeypatch):
    root, _old, state = installed
    health = guest.profile_health
    monkeypatch.setattr(guest, "profile_health", lambda config, port: {
        **health(config, port), "busy": (root / ".deploying").exists(),
    })
    result = guest.deploy(ATTEMPT, new_bundle())
    assert result["state"] == "failed"
    assert not state["calls"]
    assert not (root / ".deploying").exists()


def test_legacy_health_requires_controlled_bootstrap(installed):
    _root, _old, state = installed
    state["protocol"] = None
    result = guest.deploy(ATTEMPT, new_bundle())
    assert result["state"] == "failed"
    assert "bootstrap/recovery" in result["error"]
    assert not state["calls"]


def test_explicit_bootstrap_adopts_legacy_layout_and_preserves_prior_bundle(installed):
    root, old, state = installed
    state["protocol"] = None
    result = guest.bootstrap(ATTEMPT, new_bundle())
    assert result["state"] == "succeeded", result
    assert result["operation"] == "bootstrap"
    assert result["after"]["installed"] == new_bundle()["identity"]
    assert guest.read_identity(root / "previous") == guest.identity(old)
    assert guest.read_identity(root) == new_bundle()["identity"]
    assert state["calls"] == ["stop", "restart"]
    assert not (root / ".deploying").exists()
    assert [event["phase"] for event in result["events"]] == [
        "inspect", "interlock", "stop", "stage", "activate", "restart", "verify", "verified",
    ]


def test_bootstrap_refuses_guarded_or_unexpected_layout_without_stopping(installed):
    root, _old, state = installed
    (root / "current").symlink_to("releases/existing")
    result = guest.bootstrap(ATTEMPT, new_bundle())
    assert result["state"] == "failed"
    assert "Guarded runner layout" in result["error"]
    assert not state["calls"]


def test_bootstrap_failure_after_stop_retains_interlock(installed, monkeypatch):
    root, _old, state = installed
    monkeypatch.setattr(guest, "save_bundle", Mock(side_effect=OSError("private details")))
    result = guest.bootstrap(ATTEMPT, new_bundle())
    assert result["state"] == "uncertain"
    assert result["interlock_retained"] is True
    assert (root / ".deploying").read_text() == ATTEMPT
    assert state["calls"] == ["stop"]
    assert "private details" not in json.dumps(result)


def test_preexisting_interlock_is_never_cleared(installed):
    root, _old, state = installed
    (root / ".deploying").write_text("owner-maintenance")
    result = guest.deploy(ATTEMPT, new_bundle())
    assert result["state"] == "failed"
    assert result["interlock_retained"] is True
    assert (root / ".deploying").read_text() == "owner-maintenance"
    assert not state["calls"]


def test_replaced_marker_is_not_cleared_on_failure(installed, monkeypatch):
    root, _old, state = installed

    def replace_marker(*args):
        (root / ".deploying").write_text("separate-maintenance-owner")
        raise OSError("stage failed")

    monkeypatch.setattr(guest, "save_bundle", replace_marker)
    result = guest.deploy(ATTEMPT, new_bundle())
    assert result["state"] == "failed"
    assert result["failed_phase"] == "stage"
    assert result["interlock_retained"] is True
    assert (root / ".deploying").read_text() == "separate-maintenance-owner"
    assert not state["calls"]


def test_guest_service_commands_are_fixed_argv(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(guest.subprocess, "run", run)
    guest.systemctl("restart")
    assert run.call_args.args[0] == [
        "/usr/bin/systemctl", "restart", "neri-proxy.service", "neri-wordpress-proxy.service",
    ]
    assert "shell" not in run.call_args.kwargs


@pytest.mark.parametrize("failure", ["transfer", "stage", "hash"])
def test_pre_activation_failures_preserve_installed_bundle(installed, monkeypatch, failure):
    root, old, state = installed
    value = new_bundle()
    if failure == "transfer":
        value["files"]["proxy_core.py"] = base64.b64encode(b"corrupt").decode()
    elif failure == "stage":
        monkeypatch.setattr(guest, "save_bundle", Mock(side_effect=OSError("private transport details")))
    else:
        stage = root / "releases" / value["identity"]["release_id"].removeprefix("sha256:")
        stage.mkdir(parents=True)
        for name in guest.FILES:
            (stage / name).write_bytes(b"corrupt")
    result = guest.deploy(ATTEMPT, value)
    assert result["state"] == "failed"
    assert not state["calls"]
    assert guest.read_identity(root) == guest.identity(old)
    assert not (root / ".deploying").exists()
    assert "private transport details" not in json.dumps(result)


@pytest.mark.parametrize("failure", ["stop", "restart", "health", "installed_hash"])
def test_uncertain_activation_retains_marker_and_receipt(installed, monkeypatch, failure):
    root, old, state = installed
    systemctl = guest.systemctl

    def fail_systemctl(action):
        if action == failure:
            raise guest.DeploymentError("Service transition failed")
        systemctl(action)
        if action == "restart" and failure == "health":
            state["release"] = guest.identity(old)
        if action == "restart" and failure == "installed_hash":
            (root / "proxy_core.py").write_bytes(b"unexpected")

    monkeypatch.setattr(guest, "systemctl", fail_systemctl)
    ticks = iter([0, 31])
    monkeypatch.setattr(guest.time, "monotonic", lambda: next(ticks))
    result = guest.deploy(ATTEMPT, new_bundle())
    assert result["state"] == "uncertain", result
    assert result["interlock_retained"] is True
    assert (root / ".deploying").read_text() == ATTEMPT
    assert (root / "releases" / guest.identity(old)["release_id"].removeprefix("sha256:")).exists()
    calls = list(state["calls"])
    refused = guest.deploy("2" * 32, new_bundle())
    assert refused["state"] == "failed"
    assert refused["before"]["marker"] == ATTEMPT
    assert state["calls"] == calls


def test_later_release_uses_single_activation_without_legacy_stop(installed):
    root, _old, state = installed
    first = new_bundle()
    assert guest.deploy(ATTEMPT, first)["state"] == "succeeded"
    second = payload({name: b"third-" + name.encode() for name in guest.FILES})
    assert guest.deploy("2" * 32, second)["state"] == "succeeded"
    assert state["calls"] == ["stop", "restart", "restart"]
    assert guest.read_identity(root / "previous") == first["identity"]
    assert guest.read_identity(root) == second["identity"]


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "checkout"
    for source in deploy.SOURCES:
        path = root / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"checkout-" + path.name.encode())
    return root


class LocalGuestClient:
    def __init__(self):
        self.commands = []
        self.results = {}

    def agent_exec(self, vmid, command):
        assert vmid == "120"
        assert command[:2] == ["/usr/bin/python3", "-c"]
        assert command[2] == Path(guest.__file__).read_text()
        self.commands.append(command)
        if command[3] == "inspect":
            value, code = guest.inspect(), 0
        else:
            assert command[3] in {"bootstrap", "deploy"}
            operation = guest.bootstrap if command[3] == "bootstrap" else guest.deploy
            value = operation(command[4], json.loads(command[5]))
            code = 0 if value["state"] in {"succeeded", "noop"} else 1
        pid = len(self.commands)
        self.results[pid] = {"exited": True, "exitcode": code, "out-data": json.dumps(value)}
        return {"pid": pid}

    def agent_exec_status(self, vmid, pid):
        return self.results[pid]


def test_host_freezes_sources_before_inspection_and_uses_fixed_argv(installed, checkout, monkeypatch):
    client = LocalGuestClient()
    initial = deploy.FrozenBundle.from_checkout(checkout).payload["identity"]
    execute = client.agent_exec

    def mutate_after_freeze(vmid, command):
        result = execute(vmid, command)
        if command[3] == "inspect":
            (checkout / deploy.SOURCES[0]).write_bytes(b"later checkout change")
        return result

    monkeypatch.setattr(client, "agent_exec", mutate_after_freeze)
    monkeypatch.setattr(deploy, "ProxmoxClient", lambda: client)
    assert deploy.deploy_runner(checkout, deploy.RunnerAdapter.neri_runner_v1) == 0
    assert guest.read_identity(installed[0]) == initial
    assert [command[3] for command in client.commands] == ["inspect", "deploy"]
    record = json.loads(next((checkout / ".dev-tools" / "runner-deployments").glob("*.json")).read_text())
    assert record["state"] == "succeeded"
    assert record["guest_pid"] == 2


def test_host_bootstrap_uses_explicit_fixed_guest_action(installed, checkout, monkeypatch):
    _root, _old, state = installed
    state["protocol"] = None
    client = LocalGuestClient()
    monkeypatch.setattr(deploy, "ProxmoxClient", lambda: client)
    assert deploy.bootstrap_runner(checkout, deploy.RunnerAdapter.neri_runner_v1) == 0
    assert [command[3] for command in client.commands] == ["inspect", "bootstrap"]
    record = json.loads(next((checkout / ".dev-tools" / "runner-deployments").glob("*.json")).read_text())
    assert record["operation"] == "bootstrap"
    assert record["state"] == "succeeded"


def test_bootstrap_cli_requires_preview_token(installed, checkout, monkeypatch):
    project = service_ops.ProjectServices(
        project_id="neri", root=checkout, backend_service="backend", frontend_service="frontend",
        default_workers=(), optional_workers=(), backend_port=1, frontend_port=2,
        backend_dir=checkout / "backend", frontend_dir=checkout / "frontend", health_endpoint="/health",
        runner_adapter=deploy.RunnerAdapter.neri_runner_v1,
    )
    monkeypatch.setattr(service, "_load", lambda _: project)
    operation = Mock(return_value=0)
    monkeypatch.setattr(service, "bootstrap_runner", operation)
    runner = CliRunner()
    preview = runner.invoke(service.app, ["bootstrap-runner", "neri"])
    assert preview.exit_code == 0
    assert "BOOTSTRAP LEGACY RUNNER" in preview.output
    token = preview.output.split("--confirm ", 1)[1].strip()
    result = runner.invoke(service.app, ["bootstrap-runner", "neri", "--confirm", token])
    assert result.exit_code == 0, result.output
    operation.assert_called_once_with(checkout, deploy.RunnerAdapter.neri_runner_v1)


@pytest.mark.parametrize("failure", ["submission", "poll", "truncated", "malformed"])
def test_host_preserves_uncertainty_after_submission_without_retry(installed, checkout, monkeypatch, failure):
    client = LocalGuestClient()
    execute = client.agent_exec

    def lost(vmid, command):
        if command[3] == "deploy" and failure == "submission":
            raise ProxmoxError("private transport details")
        return execute(vmid, command)

    status = client.agent_exec_status

    def lost_status(vmid, pid):
        if pid == 2:
            if failure == "poll":
                raise ProxmoxError("private transport details")
            if failure == "truncated":
                return {**status(vmid, pid), "out-truncated": True}
            if failure == "malformed":
                return {"exited": True, "exitcode": 0, "out-data": "not json"}
        return status(vmid, pid)

    monkeypatch.setattr(client, "agent_exec", lost)
    monkeypatch.setattr(client, "agent_exec_status", lost_status)
    monkeypatch.setattr(deploy, "ProxmoxClient", lambda: client)
    assert deploy.deploy_runner(checkout, deploy.RunnerAdapter.neri_runner_v1) == 1
    record = json.loads(next((checkout / ".dev-tools" / "runner-deployments").glob("*.json")).read_text())
    assert record["state"] == "uncertain"
    assert record["observation"]["installed"] == guest.identity(installed[1])
    assert "private transport details" not in json.dumps(record)
    assert len(client.commands) <= 2


@pytest.mark.parametrize("raw,project", [
    ({"command": "anything"}, "neri"), ("other", "neri"), ("neri-runner-v1", "other"),
])
def test_manifest_cannot_supply_adapter_commands_or_other_projects(monkeypatch, tmp_path, raw, project):
    monkeypatch.setattr(service_ops, "get_project_identity", lambda _: {
        "project": {"id": project}, "services": {"runner_adapter": raw},
    })
    monkeypatch.setattr(service_ops, "get_project_identity_root", lambda _: str(tmp_path))
    with pytest.raises(service_ops.ServiceError):
        service_ops.load_project(project)


@pytest.mark.parametrize("scope,called", [("full", True), ("backend", True), ("worker", True), ("frontend", False)])
def test_lifecycle_scope_and_runner_failure_precede_host_mutations(monkeypatch, checkout, scope, called):
    project = service_ops.ProjectServices(
        project_id="neri", root=checkout, backend_service="backend", frontend_service="frontend",
        default_workers=(), optional_workers=(), backend_port=1, frontend_port=2,
        backend_dir=checkout / "backend", frontend_dir=checkout / "frontend", health_endpoint="/health",
        runner_adapter=deploy.RunnerAdapter.neri_runner_v1,
    )
    monkeypatch.setattr(service, "_load", lambda _: project)
    adapter = Mock(return_value=1)
    monkeypatch.setattr(service, "deploy_runner", adapter)
    infrastructure = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "ensure_infra", infrastructure)
    for name in ("build_frontend", "sync_systemd_units", "restart_service", "verify_health", "sync_seeds"):
        monkeypatch.setattr(service_ops, name, Mock(return_value=0))
    result = CliRunner().invoke(service.app, ["rebuild", "neri", "--scope", scope])
    assert result.exit_code == int(called), result.output
    assert adapter.call_count == int(called)
    assert infrastructure.call_count == int(not called)
    if called:
        adapter.assert_called_once_with(checkout, deploy.RunnerAdapter.neri_runner_v1)
    # Existing projects without an adapter keep the native path.
    monkeypatch.setattr(service, "_load", lambda _: replace(project, runner_adapter=None))
    result = CliRunner().invoke(service.app, ["rebuild", "neri", "--scope", "frontend"])
    assert result.exit_code == 0
