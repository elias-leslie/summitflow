"""Fixed runner deployment: real filesystem transactions, simulated guest services."""

import base64
import hashlib
import json
import os
import subprocess
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from cli.commands import service
from cli.lib import neri_runner_deploy as deploy
from cli.lib import neri_runner_guest as guest
from cli.lib import service_ops, service_release
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
    root.chmod(0o755)
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


def fixture_public_files(version="old"):
    controls = {name: ("fixture-" + name).encode() for name in guest.FIXTURE_CONTROLS if name != "fixture.lock.json"}
    lock = {
        "schema_version": "neri.wordpress-fixture.v1", "reset_version": "fixture-seed-v1",
        "wordpress": {"version": version},
        "fixture_files": {name: hashlib.sha256(value).hexdigest() for name, value in controls.items()},
    }
    lock_bytes = json.dumps(lock).encode()
    digest = hashlib.sha256(lock_bytes).hexdigest()
    profile = {
        "kind": "wordpress", "root": "/var/lib/neri-wordpress-runner",
        "receipts": "/var/lib/neri-wordpress-reset-receipts",
        "fixture_root": "/opt/neri-wordpress-fixture", "env_home": "/var/lib/neri-wordpress/wp-env",
        "runtime_user": "neri-wordpress", "reset_version": "fixture-seed-v1",
        "fixture_digest": digest, "artifact_identity": "wordpress-fixture:sha256:" + digest,
    }
    config = {"schema_version": "neri.reset-profiles.v1", "profiles": {
        "juice-shop-local-v1": {"kind": "juice-shop"},
        "wordpress-simple-page-ordering-local-v1": profile,
    }}
    return {"reset-profiles.json": json.dumps(config).encode(), "target_reset.py": b"fixed-reset-helper",
            "fixture/fixture.lock.json": lock_bytes,
            **{"fixture/" + name: value for name, value in controls.items()}}


@pytest.fixture
def fixture_installation(installed, monkeypatch, tmp_path):
    for attribute, path in (
        ("FIXTURE_ROOT", tmp_path / "fixture"), ("RESET_CONFIG", tmp_path / "etc/reset-profiles.json"),
        ("RESET_HELPER", tmp_path / "lib/target_reset.py"), ("WORDPRESS_CONFIG", tmp_path / "etc/wordpress-config.json"),
        ("RUNNER_CONFIG", tmp_path / "etc/config.json"),
    ):
        monkeypatch.setattr(guest, attribute, path)
        directory = path if attribute == "FIXTURE_ROOT" else path.parent
        directory.mkdir(exist_ok=True)
        directory.chmod(0o755)
    guest.WORDPRESS_CONFIG.parent.chmod(0o750)
    monkeypatch.setattr(guest.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid()))
    monkeypatch.setattr(guest.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=os.getgid()))
    files = fixture_public_files()
    for name, path in guest.fixture_paths().items():
        path.write_bytes(files[name])
        path.chmod(0o755 if name.endswith(".sh") else 0o644)
    private = {"api_key": "private-api-key", "nested": {"keep": ["private-value"]},
               "target_artifact_identity": guest.fixture_contents(payload(files))[2]}
    guest.WORDPRESS_CONFIG.write_text(json.dumps(private))
    guest.WORDPRESS_CONFIG.chmod(0o640)
    guest.RUNNER_CONFIG.write_bytes(b'{ "api_key": "private-juice-key", "keep": true }\n')
    guest.RUNNER_CONFIG.chmod(0o640)
    provision = Mock()
    verify = Mock()
    monkeypatch.setattr(guest, "provision_fixture", provision)
    monkeypatch.setattr(guest, "verify_fixture", verify)
    return files, private, provision, verify


def test_runner_bundle_transport_is_bounded_and_round_trips_exact_payload():
    value = payload({
        "proxy_runner.py": b"runner-source\n" * 8000,
        "proxy_core.py": b"core-source\n" * 6000,
    })
    raw = json.dumps(value, separators=(",", ":"))
    encoded = guest.encode_payload(value)

    assert guest.decode_payload(encoded) == value
    assert len(encoded) < len(raw) // 10


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
def checkout(tmp_path, fixture_installation):
    root = tmp_path / "checkout"
    for source in deploy.SOURCES:
        path = root / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"checkout-" + path.name.encode())
    for source, name in zip(deploy.FIXTURE_SOURCES, guest.FIXTURE_FILES, strict=True):
        path = root / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fixture_installation[0][name])
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
        elif command[3] == "recover-fixture":
            value = guest.recover_fixture(command[4], command[5], guest.decode_payload(command[6]))
            code = 0 if value["state"] == "succeeded" else 1
        else:
            assert command[3] in {"bootstrap", "deploy", "sync-fixture"}
            operation = {"bootstrap": guest.bootstrap, "deploy": guest.deploy, "sync-fixture": guest.sync_fixture}[command[3]]
            value = operation(command[4], guest.decode_payload(command[5]))
            code = 0 if value["state"] in {"succeeded", "noop"} else 1
        pid = len(self.commands)
        self.results[pid] = {"exited": True, "exitcode": code, "out-data": json.dumps(value)}
        return {"pid": pid}

    def agent_exec_status(self, vmid, pid):
        return self.results[pid]


def test_host_freezes_sources_before_inspection_and_uses_fixed_argv(installed, checkout, monkeypatch):
    client = LocalGuestClient()
    initial = deploy.FrozenBundle.from_checkout(checkout).payload["identity"]
    fixture_initial = deploy.FrozenFixture.from_checkout(checkout).payload["identity"]
    execute = client.agent_exec

    def mutate_after_freeze(vmid, command):
        result = execute(vmid, command)
        if command[3] == "inspect":
            (checkout / deploy.SOURCES[0]).write_bytes(b"later checkout change")
            (checkout / deploy.FIXTURE_SOURCES[0]).write_bytes(b"later public config change")
        return result

    monkeypatch.setattr(client, "agent_exec", mutate_after_freeze)
    monkeypatch.setattr(deploy, "ProxmoxClient", lambda: client)
    assert deploy.deploy_runner(checkout, deploy.RunnerAdapter.neri_runner_v1) == 0
    assert guest.read_identity(installed[0]) == initial
    assert [command[3] for command in client.commands] == ["inspect", "sync-fixture", "deploy"]
    assert guest.fixture_observation()["installed"] == fixture_initial
    record = json.loads(next((checkout / ".dev-tools" / "runner-deployments").glob("*.json")).read_text())
    assert record["state"] == "succeeded"
    assert record["guest_pid"] == 3
    assert record["fixture"]["expected"] == fixture_initial


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
        if pid == 3:
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
    assert len(client.commands) <= 3
    assert record["guest_processes"]["inspect"]["pid"] == 1
    assert record["guest_processes"]["inspect"]["state"] == "exited"
    if failure == "submission":
        assert record["guest_action"] == "deploy"
        assert record["guest_pid"] is None
        assert record["guest_processes"]["deploy"] == {
            "state": "submitting", "pid": None,
        }
    else:
        assert record["guest_pid"] == 3
        assert record["guest_processes"]["deploy"]["pid"] == 3


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
    stable = checkout / "accepted-source"
    release = service_release.PreparedRelease(
        project_id="neri",
        build_id="b" * 32,
        source=service_release.AcceptedSource(
            acceptance_id="acceptance-test",
            source_commit="c" * 40,
            source_tree="d" * 40,
        ),
        release_root=stable.parent,
        source_root=stable,
        receipt_path=stable.parent / "deployment.json",
    )

    def prepare(current, _receipt=None):
        return release, replace(
            current,
            root=stable,
            backend_dir=stable / "backend",
            frontend_dir=stable / "frontend",
            host_config_root=current.root,
            durable_data_root=current.root / "data",
        )

    monkeypatch.setattr(service_ops, "prepare_accepted_release", prepare)
    monkeypatch.setattr(service_release, "deployment_lock", lambda _project: nullcontext())
    monkeypatch.setattr(service_release, "mark_phase", Mock())
    monkeypatch.setattr(service_release, "fail_release", Mock())
    monkeypatch.setattr(service_release, "complete_release", Mock())
    monkeypatch.setattr(
        service_release,
        "publish_deployment_result",
        lambda *_args, **_kwargs: {
            "artifact": str(release.receipt_path),
            "deployment_id": "e" * 64,
        },
    )
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
        adapter.assert_called_once_with(stable, deploy.RunnerAdapter.neri_runner_v1)
    # Existing projects without an adapter keep the native path.
    monkeypatch.setattr(service, "_load", lambda _: replace(project, runner_adapter=None))
    result = CliRunner().invoke(service.app, ["rebuild", "neri", "--scope", "frontend"])
    assert result.exit_code == 0


def test_changed_fixture_provisions_verifies_and_preserves_private_config(installed, fixture_installation):
    root, _old_source, state = installed
    old, private, provision, verify = fixture_installation
    old_details = guest.WORDPRESS_CONFIG.stat()
    files = fixture_public_files("new")
    result = guest.sync_fixture(ATTEMPT, payload(files))

    assert result["state"] == "succeeded", result
    assert result["verified"] is True
    assert result["after"]["installed"] == guest.identity(files)
    assert result["after"]["artifact_identity"] == guest.fixture_contents(payload(files))[2]
    updated = json.loads(guest.WORDPRESS_CONFIG.read_bytes())
    assert updated == {**private, "target_artifact_identity": result["artifact_identity"]}
    details = guest.WORDPRESS_CONFIG.stat()
    assert (details.st_mode, details.st_uid, details.st_gid) == (old_details.st_mode, old_details.st_uid, old_details.st_gid)
    assert state["calls"] == ["stop", "restart"]
    provision.assert_called_once_with()
    verify.assert_called_once_with()
    backup = Path(result["backup"])
    assert backup.stat().st_mode & 0o777 == 0o700
    private_backup = backup / "private-wordpress-config.json"
    assert private_backup.stat().st_mode & 0o777 == 0o600
    assert json.loads(private_backup.read_bytes()) == private
    assert (backup / "fixture_fixture.lock.json").read_bytes() == old["fixture/fixture.lock.json"]
    assert "private-api-key" not in json.dumps(result)
    assert "private-value" not in json.dumps(result)
    assert not (root / ".deploying").exists()
    assert json.loads((root / "deployments" / (ATTEMPT + "-fixture.json")).read_text()) == result
    assert guest.FILES == ("proxy_runner.py", "proxy_core.py")


def test_identical_fixture_is_verified_noop_without_reseed_or_restart(installed, fixture_installation):
    root, _old_source, state = installed
    files, _private, provision, verify = fixture_installation
    result = guest.sync_fixture(ATTEMPT, payload(files))
    assert result["state"] == "noop", result
    assert result["verified"] is True
    assert result["after"]["installed"] == guest.identity(files)
    assert state["calls"] == []
    provision.assert_not_called()
    verify.assert_called_once_with()
    assert not (root / ".deploying").exists()
    assert "backup" not in result


@pytest.mark.parametrize("changed", [False, True])
def test_legacy_config_adoption_preserves_private_bytes_and_provisions_only_changed_digest(
    installed, fixture_installation, changed,
):
    root, _source, state = installed
    old, _private, provision, verify = fixture_installation
    directory = guest.WORDPRESS_CONFIG.parent
    directory.chmod(0o700)
    guest.RUNNER_CONFIG.chmod(0o600)
    private_bytes = {path: path.read_bytes() for path in (guest.RUNNER_CONFIG, guest.WORDPRESS_CONFIG)}
    old_runner_inode = guest.RUNNER_CONFIG.stat().st_ino
    tls = directory / "tls"
    tls.mkdir(mode=0o700)
    certificate = tls / "private.pem"
    certificate.write_bytes(b"private-tls-key")
    certificate.chmod(0o600)
    tls_before = tls.stat(), certificate.stat(), certificate.read_bytes()
    files = fixture_public_files("new") if changed else old

    result = guest.sync_fixture(ATTEMPT, payload(files))

    assert result["state"] == "succeeded", result
    assert result["configuration_adopted"] is True
    assert state["calls"] == ["stop", "restart"]
    assert provision.call_count == int(changed)
    verify.assert_called_once_with()
    assert guest.RUNNER_CONFIG.read_bytes() == private_bytes[guest.RUNNER_CONFIG]
    assert guest.RUNNER_CONFIG.stat().st_ino != old_runner_inode
    assert directory.stat().st_mode & 0o777 == 0o750
    for path in private_bytes:
        details = path.stat()
        assert (details.st_uid, details.st_gid, details.st_mode & 0o777) == (os.getuid(), os.getgid(), 0o640)
        backup = Path(result["backup"]) / ("private-" + path.name)
        assert backup.read_bytes() == private_bytes[path]
        assert backup.stat().st_mode & 0o777 == 0o600
    if not changed:
        assert guest.WORDPRESS_CONFIG.read_bytes() == private_bytes[guest.WORDPRESS_CONFIG]
        assert "install" not in [event["phase"] for event in result["events"]]
    assert (tls.stat(), certificate.stat(), certificate.read_bytes()) == tls_before
    assert guest.fixture_observation()["installed"] == guest.identity(files)
    assert not (root / ".deploying").exists()
    receipt = json.dumps(result)
    for secret in ("private-api-key", "private-juice-key", "private-value", "private-tls-key"):
        assert secret not in receipt

    result = guest.sync_fixture("2" * 32, payload(files))
    assert result["state"] == "noop", result
    assert provision.call_count == int(changed)
    assert state["calls"] == ["stop", "restart"]


@pytest.mark.parametrize("fault", ["directory-mode", "directory-symlink", "runner-mode",
                                   "runner-symlink", "runner-hardlink", "owner", "group", "missing-account"])
def test_config_adoption_refuses_unsupported_layout_before_service_effects(
    installed, fixture_installation, monkeypatch, fault,
):
    root, _source, state = installed
    files, _private, provision, verify = fixture_installation
    if fault == "directory-mode":
        guest.WORDPRESS_CONFIG.parent.chmod(0o755)
    elif fault == "directory-symlink":
        directory = guest.WORDPRESS_CONFIG.parent
        directory.rename(directory.with_name("moved"))
        directory.symlink_to(directory.with_name("moved"), target_is_directory=True)
    elif fault == "runner-mode":
        guest.RUNNER_CONFIG.chmod(0o660)
    elif fault == "runner-symlink":
        moved = guest.RUNNER_CONFIG.with_suffix(".private")
        guest.RUNNER_CONFIG.rename(moved)
        guest.RUNNER_CONFIG.symlink_to(moved)
    elif fault == "runner-hardlink":
        os.link(guest.RUNNER_CONFIG, guest.RUNNER_CONFIG.with_suffix(".link"))
    elif fault == "owner":
        guest.WORDPRESS_CONFIG.parent.chmod(0o700)
        guest.RUNNER_CONFIG.chmod(0o600)
        monkeypatch.setattr(guest.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=os.getuid() + 1, pw_gid=os.getgid()))
    elif fault == "group":
        monkeypatch.setattr(guest.grp, "getgrnam", lambda _: SimpleNamespace(gr_gid=os.getgid() + 1))
    else:
        monkeypatch.setattr(guest.pwd, "getpwnam", Mock(side_effect=KeyError("private account details")))
    result = guest.sync_fixture(ATTEMPT, payload(files))
    assert result["state"] == "failed", result
    assert not state["calls"]
    assert not (root / ".deploying").exists()
    assert "backup" not in result
    provision.assert_not_called()
    verify.assert_not_called()
    assert "private account details" not in json.dumps(result)


@pytest.mark.parametrize("path_name", ["RUNNER_CONFIG", "WORDPRESS_CONFIG", "directory", "public-lock"])
@pytest.mark.parametrize("when", ["interlock", "stop"])
def test_config_adoption_revalidates_swapped_paths_and_retains_uncertain_marker(
    installed, fixture_installation, monkeypatch, path_name, when,
):
    root, _source, state = installed
    files, _private, provision, verify = fixture_installation
    guest.WORDPRESS_CONFIG.parent.chmod(0o700)
    guest.RUNNER_CONFIG.chmod(0o600)
    swapped = False

    def swap():
        nonlocal swapped
        if swapped:
            return
        swapped = True
        if path_name == "directory":
            guest.WORDPRESS_CONFIG.parent.chmod(0o750)
        else:
            path = (guest.FIXTURE_ROOT / "fixture.lock.json" if path_name == "public-lock"
                    else getattr(guest, path_name))
            replacement = path.with_suffix(".replacement")
            replacement.write_bytes(path.read_bytes())
            replacement.chmod(path.stat().st_mode & 0o777)
            replacement.replace(path)

    health = guest.profile_health
    services = guest.systemctl

    def observe(config, port):
        if when == "interlock" and (root / ".deploying").exists():
            swap()
        return health(config, port)

    def service_action(action):
        services(action)
        if when == "stop" and action == "stop":
            swap()

    monkeypatch.setattr(guest, "profile_health", observe)
    monkeypatch.setattr(guest, "systemctl", service_action)
    result = guest.sync_fixture(ATTEMPT, payload(files))
    assert result["state"] == ("uncertain" if when == "stop" else "failed"), result
    assert result["interlock_retained"] is (when == "stop")
    assert (root / ".deploying").exists() is (when == "stop")
    assert state["calls"] == (["stop"] if when == "stop" else [])
    provision.assert_not_called()
    verify.assert_not_called()


def test_config_adoption_partial_replacement_failure_keeps_backup_and_interlock(
    installed, fixture_installation, monkeypatch,
):
    root, _source, state = installed
    files, _private, provision, verify = fixture_installation
    guest.WORDPRESS_CONFIG.parent.chmod(0o700)
    guest.RUNNER_CONFIG.chmod(0o600)
    replace = guest.replace_file

    def interrupt(path, contents, mode, uid, gid):
        if path == guest.RUNNER_CONFIG:
            raise OSError("private adoption details")
        replace(path, contents, mode, uid, gid)

    monkeypatch.setattr(guest, "replace_file", interrupt)
    result = guest.sync_fixture(ATTEMPT, payload(files))
    assert result["state"] == "uncertain", result
    assert result["failed_phase"] == "adopt-configuration"
    assert (root / ".deploying").read_text() == ATTEMPT
    assert state["calls"] == ["stop"]
    assert guest.WORDPRESS_CONFIG.parent.stat().st_mode & 0o777 == 0o750
    assert (Path(result["backup"]) / "private-config.json").read_bytes() == guest.RUNNER_CONFIG.read_bytes()
    assert "private adoption details" not in json.dumps(result)
    provision.assert_not_called()
    verify.assert_not_called()
    refused = guest.sync_fixture("2" * 32, payload(files))
    assert refused["state"] == "failed"
    assert refused["interlock_retained"] is True


@pytest.mark.parametrize("change", ["private-artifact", "reset-helper", "missing-helper", "script-mode"])
def test_same_lock_digest_updates_metadata_without_reseeding(installed, fixture_installation, change):
    _root, _old_source, state = installed
    files, private, provision, verify = fixture_installation
    files = dict(files)
    if change == "private-artifact":
        guest.WORDPRESS_CONFIG.write_text(json.dumps({**private, "target_artifact_identity": "wordpress-fixture:sha256:" + "0" * 64}))
    elif change == "reset-helper":
        files["target_reset.py"] = b"updated-fixed-helper"
    elif change == "missing-helper":
        guest.RESET_HELPER.unlink()
    else:
        (guest.FIXTURE_ROOT / "seed.sh").chmod(0o644)
    result = guest.sync_fixture(ATTEMPT, payload(files))
    assert result["state"] == "succeeded", result
    assert state["calls"] == ["stop", "restart"]
    provision.assert_not_called()
    verify.assert_called_once_with()


@pytest.mark.parametrize("fault", ["extra", "missing", "transfer-hash", "control-hash", "profile-artifact", "profile-path", "control-allowlist"])
def test_fixture_contract_errors_refuse_before_mutation(installed, fixture_installation, fault):
    root, _source, state = installed
    old, _private, provision, verify = fixture_installation
    files = fixture_public_files("new")
    if fault == "extra":
        files["fixture/arbitrary.sh"] = b"caller code"
    elif fault == "missing":
        del files["fixture/seed.sh"]
    elif fault == "control-hash":
        files["fixture/seed.sh"] = b"corrupt"
    elif fault in {"profile-artifact", "profile-path"}:
        config = json.loads(files["reset-profiles.json"])
        profile = config["profiles"]["wordpress-simple-page-ordering-local-v1"]
        profile["artifact_identity" if fault == "profile-artifact" else "fixture_root"] = "invalid"
        files["reset-profiles.json"] = json.dumps(config).encode()
    elif fault == "control-allowlist":
        lock = json.loads(files["fixture/fixture.lock.json"])
        lock["fixture_files"]["../arbitrary.sh"] = "0" * 64
        files["fixture/fixture.lock.json"] = json.dumps(lock).encode()
        config = json.loads(files["reset-profiles.json"])
        profile = config["profiles"]["wordpress-simple-page-ordering-local-v1"]
        profile["fixture_digest"] = hashlib.sha256(files["fixture/fixture.lock.json"]).hexdigest()
        profile["artifact_identity"] = "wordpress-fixture:sha256:" + profile["fixture_digest"]
        files["reset-profiles.json"] = json.dumps(config).encode()
    value = payload(files)
    if fault == "transfer-hash":
        value["files"]["target_reset.py"] = base64.b64encode(b"corrupt").decode()
    result = guest.sync_fixture(ATTEMPT, value)
    assert result["state"] == "failed", result
    assert guest.fixture_observation()["installed"] == guest.identity(old)
    assert state["calls"] == []
    assert not (root / ".deploying").exists()
    provision.assert_not_called()
    verify.assert_not_called()


@pytest.mark.parametrize("profile,unsettled", [(0, False), (1, False), (1, True)])
def test_fixture_sync_refuses_either_busy_profile_or_unsettled_reset(installed, fixture_installation, monkeypatch, profile, unsettled):
    root, _source, state = installed
    old, _private, provision, verify = fixture_installation
    health = guest.profile_health

    def busy(config, port):
        value = health(config, port)
        if port == guest.PROFILES[profile][2]:
            # The real runner includes an unsettled reset in this health field.
            value.update(busy=True, stopped=unsettled)
        return value

    monkeypatch.setattr(guest, "profile_health", busy)
    result = guest.sync_fixture(ATTEMPT, payload(fixture_public_files("new")))
    assert result["state"] == "failed"
    assert "busy" in result["error"]
    assert guest.fixture_observation()["installed"] == guest.identity(old)
    assert not state["calls"]
    assert not (root / ".deploying").exists()
    provision.assert_not_called()
    verify.assert_not_called()


@pytest.mark.parametrize("fault", ["stop", "install", "private-config", "provision", "verify", "restart"])
def test_fixture_effect_uncertainty_retains_interlock_and_prevents_retry(installed, fixture_installation, monkeypatch, fault):
    root, _source, _state = installed
    _old, _private, provision, verify = fixture_installation
    service_action = guest.systemctl
    replace = guest.replace_file

    def services(action):
        if action == fault:
            raise OSError("private service details")
        service_action(action)

    def interrupt(path, contents, mode, uid, gid):
        if ((fault == "install" and path == guest.RESET_HELPER)
                or (fault == "private-config" and path == guest.WORDPRESS_CONFIG)):
            raise OSError("private installation details")
        replace(path, contents, mode, uid, gid)

    monkeypatch.setattr(guest, "systemctl", services)
    monkeypatch.setattr(guest, "replace_file", interrupt)
    if fault == "provision":
        provision.side_effect = subprocess.TimeoutExpired(["private process"], 900, output=b"private output")
    if fault == "verify":
        verify.side_effect = OSError("private verification details")
    value = payload(fixture_public_files("new"))
    result = guest.sync_fixture(ATTEMPT, value)
    assert result["state"] == "uncertain", result
    assert result["interlock_retained"] is True
    assert (root / ".deploying").read_text() == ATTEMPT
    assert Path(result["backup"]).is_dir()
    assert "private-api-key" not in json.dumps(result)
    assert "private output" not in json.dumps(result)
    assert "private installation details" not in json.dumps(result)
    calls = provision.call_count, verify.call_count
    refused = guest.sync_fixture("2" * 32, value)
    assert refused["state"] == "failed"
    assert refused["interlock_retained"] is True
    assert (provision.call_count, verify.call_count) == calls
    with pytest.raises(guest.DeploymentError, match="already exists"):
        guest.sync_fixture(ATTEMPT, value)


@pytest.mark.parametrize("fault", ["symlink", "writable", "hardlink"])
def test_fixture_sync_rejects_unprotected_private_config(installed, fixture_installation, fault):
    root, _source, state = installed
    if fault == "symlink":
        moved = guest.WORDPRESS_CONFIG.with_suffix(".private")
        guest.WORDPRESS_CONFIG.rename(moved)
        guest.WORDPRESS_CONFIG.symlink_to(moved)
    elif fault == "writable":
        guest.WORDPRESS_CONFIG.chmod(0o660)
    else:
        os.link(guest.WORDPRESS_CONFIG, guest.WORDPRESS_CONFIG.with_suffix(".link"))
    result = guest.sync_fixture(ATTEMPT, payload(fixture_public_files("new")))
    assert result["state"] == "failed"
    assert not state["calls"]
    assert not (root / ".deploying").exists()


def test_fixture_commands_are_fixed_and_sanitize_output(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "private output", "private stderr"))
    monkeypatch.setattr(guest.subprocess, "run", run)
    guest.provision_fixture()
    assert run.call_args.args[0] == ["/usr/bin/bash", "/opt/neri-wordpress-fixture/setup.sh"]
    assert "shell" not in run.call_args.kwargs
    guest.verify_fixture()
    command = run.call_args.args[0]
    assert command[:3] == ["/usr/bin/python3", "-B", "-c"]
    assert "helper.wordpress_state(helper.wordpress_lock())" in command[3]
    assert "helper.main" not in command[3]
    run.return_value = subprocess.CompletedProcess([], 1, "private output", "private stderr")
    with pytest.raises(guest.DeploymentError, match="provisioning failed") as failure:
        guest.provision_fixture()
    assert "private" not in str(failure.value)


def test_host_fixture_failure_stops_before_source_deploy(installed, fixture_installation, checkout, monkeypatch):
    client = LocalGuestClient()
    for source, name in zip(deploy.FIXTURE_SOURCES, guest.FIXTURE_FILES, strict=True):
        (checkout / source).write_bytes(fixture_public_files("new")[name])
    fixture_installation[2].side_effect = OSError("private provisioning details")
    monkeypatch.setattr(deploy, "ProxmoxClient", lambda: client)
    assert deploy.deploy_runner(checkout, deploy.RunnerAdapter.neri_runner_v1) == 1
    assert [command[3] for command in client.commands] == ["inspect", "sync-fixture"]
    assert guest.read_identity(installed[0]) == guest.identity(installed[1])
    record = json.loads(next((checkout / ".dev-tools/runner-deployments").glob("*.json")).read_text())
    assert record["state"] == "uncertain"
    assert record["fixture"]["interlock_retained"] is True
    assert "private provisioning details" not in json.dumps(record)


def test_host_rejects_invalid_fixture_before_guest_submission(checkout, monkeypatch):
    (checkout / "scripts/lab-vm/wordpress-fixture/seed.sh").write_bytes(b"corrupt")
    client = Mock()
    monkeypatch.setattr(deploy, "ProxmoxClient", client)
    assert deploy.deploy_runner(checkout, deploy.RunnerAdapter.neri_runner_v1) == 1
    client.assert_not_called()


@pytest.mark.parametrize("operation", ["sync_fixture", "bootstrap", "deploy"])
@pytest.mark.parametrize("existing", [False, True])
def test_deployment_lock_loser_preserves_receipt_and_has_no_actions(installed, fixture_installation, monkeypatch, operation, existing):
    root, _source, state = installed
    receipts = root / "deployments"
    receipts.mkdir(mode=0o755)
    path = receipts / (ATTEMPT + ("-fixture.json" if operation == "sync_fixture" else ".json"))
    original = b'{"state":"running","owner":"original-attempt"}\n'
    if existing:
        path.write_bytes(original)
    marker = root / ".deploying"
    marker.write_text("other-attempt")
    record = Mock()
    inspection = Mock()
    monkeypatch.setattr(guest, "atomic_json", record)
    monkeypatch.setattr(guest, "inspect", inspection)
    value = payload(fixture_public_files("new")) if operation == "sync_fixture" else new_bundle()

    with (root / ".deployment-lock").open("a") as owner:
        guest.fcntl.flock(owner, guest.fcntl.LOCK_EX | guest.fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            getattr(guest, operation)(ATTEMPT, value)

    if existing:
        assert path.read_bytes() == original
    else:
        assert not path.exists()
    assert list(receipts.iterdir()) == ([path] if existing else [])
    assert marker.read_text() == "other-attempt"
    assert state["calls"] == []
    record.assert_not_called()
    inspection.assert_not_called()
    fixture_installation[2].assert_not_called()
    fixture_installation[3].assert_not_called()


@pytest.mark.parametrize("operation", ["sync_fixture", "bootstrap", "deploy"])
def test_receipt_created_before_lock_acquisition_is_rechecked_and_preserved(installed, fixture_installation, monkeypatch, operation):
    root, _source, state = installed
    receipts = root / "deployments"
    receipts.mkdir(mode=0o755)
    path = receipts / (ATTEMPT + ("-fixture.json" if operation == "sync_fixture" else ".json"))
    original = b'{"state":"succeeded","owner":"completed-while-waiting"}\n'
    flock = guest.fcntl.flock

    def complete_prior_attempt(lock, mode):
        flock(lock, mode)
        path.write_bytes(original)

    monkeypatch.setattr(guest.fcntl, "flock", complete_prior_attempt)
    record = Mock()
    inspection = Mock()
    monkeypatch.setattr(guest, "atomic_json", record)
    monkeypatch.setattr(guest, "inspect", inspection)
    value = payload(fixture_public_files("new")) if operation == "sync_fixture" else new_bundle()
    with pytest.raises(guest.DeploymentError, match="already exists"):
        getattr(guest, operation)(ATTEMPT, value)

    assert path.read_bytes() == original
    assert list(receipts.iterdir()) == [path]
    assert state["calls"] == []
    assert not (root / ".deploying").exists()
    record.assert_not_called()
    inspection.assert_not_called()
    fixture_installation[2].assert_not_called()
    fixture_installation[3].assert_not_called()


@pytest.fixture
def retained_fixture(installed, fixture_installation):
    root, _source, state = installed
    _old, _private, provision, verify = fixture_installation
    verify.side_effect = guest.DeploymentError("WordPress fixture verification failed")
    original = guest.sync_fixture(ATTEMPT, payload(fixture_public_files("provisioned")))
    assert original["state"] == "uncertain", original
    assert original["failed_phase"] == "verify-fixture"
    (root / "deployments" / (ATTEMPT + "-fixture.json")).chmod(0o644)
    provision.assert_called_once_with()
    verify.side_effect = None
    provision.reset_mock()
    verify.reset_mock()
    state["calls"].clear()
    return original


def test_fixture_recovery_preserves_original_backup_and_secrets_without_provision(
    installed, fixture_installation, retained_fixture,
):
    root, source, state = installed
    _old, _private, provision, verify = fixture_installation
    original_path = root / "deployments" / (ATTEMPT + "-fixture.json")
    original_bytes = original_path.read_bytes()
    backup = Path(retained_fixture["backup"])
    backup_bytes = {path.name: path.read_bytes() for path in backup.iterdir()}
    private_before = json.loads(guest.WORDPRESS_CONFIG.read_bytes())
    runner_before = guest.RUNNER_CONFIG.read_bytes()
    files = fixture_public_files("revised-verification-pins")
    result = guest.recover_fixture(ATTEMPT, "2" * 32, payload(files))
    assert result["state"] == "succeeded", result
    assert result["operation"] == "recover-fixture"
    assert result["original_attempt"] == ATTEMPT
    assert result["original_receipt"] == {
        "path": str(original_path), "sha256": hashlib.sha256(original_bytes).hexdigest(),
    }
    assert result["original_backup"] == str(backup)
    assert original_path.read_bytes() == original_bytes
    assert {path.name: path.read_bytes() for path in backup.iterdir()} == backup_bytes
    assert guest.RUNNER_CONFIG.read_bytes() == runner_before
    assert json.loads(guest.WORDPRESS_CONFIG.read_bytes()) == {
        **private_before, "target_artifact_identity": result["artifact_identity"],
    }
    assert guest.read_identity(root) == guest.identity(source)
    assert result["after"]["installed"] == guest.identity(files)
    assert result["after"]["artifact_identity"] == guest.fixture_contents(payload(files))[2]
    guest.require_release(result["runner_after"], guest.identity(source), blocked=True)
    assert result["verified"] is True
    assert result["interlock_retained"] is False
    assert not (root / ".deploying").exists()
    assert state["calls"] == ["restart"]
    recovery_path = root / "deployments" / ("2" * 32 + "-fixture-recovery.json")
    envelope = json.loads(recovery_path.read_bytes())
    assert envelope["state"] == "verified"
    assert guest.staged_fixture_receipt(recovery_path.read_bytes()) == result
    assert envelope["final_receipt"] == result
    assert recovery_path.stat().st_mode & 0o777 == 0o644
    assert recovery_path.stat().st_uid == guest.PRIVILEGED_UID
    provision.assert_not_called()
    verify.assert_called_once_with()
    for secret in ("private-api-key", "private-juice-key", "private-value"):
        assert secret not in json.dumps(result)


def test_fixture_recovery_accepts_provisioning_failure_without_reprovision(
    installed, fixture_installation, monkeypatch,
):
    root, _source, state = installed
    _old, _private, provision, verify = fixture_installation
    provision.side_effect = guest.DeploymentError("Fixed WordPress fixture provisioning failed")
    original = guest.sync_fixture(ATTEMPT, payload(fixture_public_files("broken-provision")))
    assert original["state"] == "uncertain", original
    assert original["failed_phase"] == "provision"
    assert [event["phase"] for event in original["events"]][-2:] == ["provision", "failed"]
    (root / "deployments" / (ATTEMPT + "-fixture.json")).chmod(0o644)
    provision.side_effect = None
    provision.reset_mock()
    state["calls"].clear()
    restore = Mock()
    monkeypatch.setattr(guest, "restore_fixture_dependencies", restore)

    repaired = guest.recover_fixture(
        ATTEMPT, "2" * 32, payload(fixture_public_files("offline-compatible")),
    )

    assert repaired["state"] == "succeeded", repaired
    assert repaired["verified"] is True
    assert repaired["interlock_retained"] is False
    assert not (root / ".deploying").exists()
    assert state["calls"] == ["restart"]
    provision.assert_not_called()
    restore.assert_called_once_with()
    verify.assert_called_once_with()


def test_fixture_dependency_restoration_is_offline_and_skips_scripts(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, b"", b""))
    monkeypatch.setattr(guest.subprocess, "run", run)

    guest.restore_fixture_dependencies()

    assert run.call_args.args[0] == ["/usr/bin/npm", "ci", "--offline", "--ignore-scripts"]
    assert run.call_args.kwargs == {
        "cwd": guest.FIXTURE_ROOT,
        "env": {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": "/root",
        },
        "capture_output": True,
        "timeout": 900,
        "check": False,
    }


@pytest.mark.parametrize("fault", ["marker", "receipt-attempt", "adapter", "operation", "state", "failed-phase",
                                   "no-provision", "wrong-order", "backup", "receipt-symlink", "marker-symlink",
                                   "busy", "unblocked", "legacy", "payload"])
def test_fixture_recovery_requires_exact_original_failure_before_mutation(
    installed, fixture_installation, retained_fixture, monkeypatch, fault,
):
    root, _source, state = installed
    _old, _private, provision, verify = fixture_installation
    original_path = root / "deployments" / (ATTEMPT + "-fixture.json")
    marker = root / ".deploying"
    original = dict(retained_fixture)
    value = payload(fixture_public_files("revised"))
    field_faults = {"receipt-attempt": ("attempt", "3" * 32), "adapter": ("adapter", "other"),
                    "operation": ("operation", "deploy"), "state": ("state", "succeeded"),
                    "failed-phase": ("failed_phase", "provision"), "backup": ("backup", "/arbitrary")}
    if fault in field_faults:
        field, wrong = field_faults[fault]
        original[field] = wrong
        original_path.write_text(json.dumps(original))
    elif fault in {"no-provision", "wrong-order"}:
        original["events"] = [{"phase": name} for name in (
            ["verify-fixture", "failed"] if fault == "no-provision" else ["verify-fixture", "provision", "failed"])]
        original_path.write_text(json.dumps(original))
    elif fault == "marker":
        marker.write_text("3" * 32)
    elif fault in {"receipt-symlink", "marker-symlink"}:
        path = original_path if fault == "receipt-symlink" else marker
        moved = path.with_suffix(".moved")
        path.rename(moved)
        path.symlink_to(moved)
    elif fault == "busy":
        state["busy"] = True
    elif fault == "unblocked":
        observe = guest.inspect
        def unblocked():
            result = observe()
            for profile in result["profiles"].values():
                profile["deployment_blocked"] = False
            return result
        monkeypatch.setattr(guest, "inspect", unblocked)
    elif fault == "legacy":
        guest.WORDPRESS_CONFIG.parent.chmod(0o700)
        guest.RUNNER_CONFIG.chmod(0o600)
    else:
        value["files"]["fixture/seed.sh"] = base64.b64encode(b"invalid").decode()
    before = {path: path.read_bytes() for path in guest.fixture_paths().values()}
    private_before = guest.WORDPRESS_CONFIG.read_bytes()
    original_bytes, marker_bytes = original_path.read_bytes(), marker.read_bytes()
    result = guest.recover_fixture(ATTEMPT, "2" * 32, value)
    assert result["state"] == "uncertain", result
    assert result["interlock_retained"] is (fault not in {"marker", "marker-symlink"})
    assert result["marker_conflict"] is (fault in {"marker", "marker-symlink"})
    assert original_path.read_bytes() == original_bytes
    assert marker.read_bytes() == marker_bytes
    assert {path: path.read_bytes() for path in guest.fixture_paths().values()} == before
    assert guest.WORDPRESS_CONFIG.read_bytes() == private_before
    assert state["calls"] == []
    provision.assert_not_called()
    verify.assert_not_called()


@pytest.mark.parametrize("attempt", ["short", "F" * 32, "../" + "1" * 32, ATTEMPT])
def test_fixture_recovery_rejects_invalid_recovery_identity(installed, fixture_installation, retained_fixture, attempt):
    with pytest.raises(guest.DeploymentError, match="Invalid"):
        guest.recover_fixture(ATTEMPT, attempt, payload(fixture_public_files("revised")))


def test_fixture_recovery_rejects_partial_health_instead_of_using_stopped_service_fallback(installed, monkeypatch):
    root, _source, _state = installed
    (root / ".deploying").write_text(ATTEMPT)
    observation = guest.inspect()
    observation["profiles"][guest.PROFILES[0][0]] = {"error": "Runner health unavailable"}
    check = Mock()
    monkeypatch.setattr(guest.subprocess, "run", check)
    with pytest.raises(guest.DeploymentError, match="Partial runner health"):
        guest.require_recovery_stopped(observation)
    check.assert_not_called()


@pytest.mark.parametrize("fault", ["install", "verify", "restart", "running-release", "marker-replaced", "receipt-write"])
def test_fixture_recovery_failure_retains_marker_and_original(
    installed, fixture_installation, retained_fixture, monkeypatch, fault,
):
    root, _source, state = installed
    _old, _private, provision, verify = fixture_installation
    original_path = root / "deployments" / (ATTEMPT + "-fixture.json")
    original_bytes = original_path.read_bytes()
    if fault == "install":
        monkeypatch.setattr(guest, "replace_file", Mock(side_effect=OSError("private installation details")))
    elif fault == "verify":
        verify.side_effect = RuntimeError("private verifier details")
    elif fault == "restart":
        monkeypatch.setattr(guest, "systemctl", Mock(side_effect=RuntimeError("private restart details")))
    elif fault in {"running-release", "marker-replaced"}:
        restart = guest.systemctl
        def change_after_restart(action):
            restart(action)
            if fault == "running-release":
                state["release"] = {"release_id": "wrong"}
            else:
                (root / ".deploying").write_text("3" * 32)
        monkeypatch.setattr(guest, "systemctl", change_after_restart)
        ticks = iter(range(0, 1000, 60))
        monkeypatch.setattr(guest.time, "monotonic", lambda: next(ticks))
    else:
        replace = guest.replace_file
        def fail_success_receipt(path, contents, mode, uid, gid):
            if path == root / ".deploying":
                raise OSError("private durable receipt details")
            replace(path, contents, mode, uid, gid)
        monkeypatch.setattr(guest, "replace_file", fail_success_receipt)
    result = guest.recover_fixture(ATTEMPT, "2" * 32, payload(fixture_public_files("revised")))
    assert result["state"] == "uncertain", result
    assert result["interlock_retained"] is (fault != "marker-replaced")
    assert result["marker_conflict"] is (fault == "marker-replaced")
    assert (root / ".deploying").read_text() == ("3" * 32 if fault == "marker-replaced" else ATTEMPT)
    assert original_path.read_bytes() == original_bytes
    provision.assert_not_called()
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize("when", ["verify", "restart"])
@pytest.mark.parametrize("change", ["missing", "other-owner"])
def test_fixture_recovery_restores_missing_owned_marker_and_reports_foreign_owner_conflict(
    installed, fixture_installation, retained_fixture, monkeypatch, when, change,
):
    root, _source, state = installed
    marker = root / ".deploying"
    original_path = root / "deployments" / (ATTEMPT + "-fixture.json")
    original_bytes = original_path.read_bytes()
    def mutate_marker():
        marker.unlink()
        if change == "other-owner":
            marker.write_text("3" * 32)
            marker.chmod(0o644)
    if when == "verify":
        fixture_installation[3].side_effect = mutate_marker
    else:
        restart = guest.systemctl
        def restarted(action):
            restart(action)
            mutate_marker()
        monkeypatch.setattr(guest, "systemctl", restarted)
    result = guest.recover_fixture(ATTEMPT, "2" * 32, payload(fixture_public_files("revised")))
    assert result["state"] == "uncertain", result
    assert result["interlock_retained"] is (change == "missing")
    assert result["marker_conflict"] is (change == "other-owner")
    assert marker.read_text() == (ATTEMPT if change == "missing" else "3" * 32)
    assert marker.stat().st_mode & 0o777 == 0o644
    assert original_path.read_bytes() == original_bytes
    assert state["calls"] == ([] if when == "verify" else ["restart"])
    fixture_installation[2].assert_not_called()


@pytest.mark.parametrize("when", ["before-rename", "after-rename"])
def test_fixture_recovery_atomic_release_has_durable_completion_or_owned_marker_after_hard_stop(
    installed, fixture_installation, retained_fixture, monkeypatch, when,
):
    root, _source, _state = installed
    marker = root / ".deploying"
    recovery_path = root / "deployments" / ("2" * 32 + "-fixture-recovery.json")
    replace = guest.os.replace
    def interrupt_release(source, destination):
        if source == marker and destination == recovery_path:
            if when == "after-rename":
                replace(source, destination)
            raise SystemExit("simulated hard process termination")
        replace(source, destination)
    monkeypatch.setattr(guest.os, "replace", interrupt_release)
    with pytest.raises(SystemExit, match="hard process termination"):
        guest.recover_fixture(ATTEMPT, "2" * 32, payload(fixture_public_files("revised")))
    if when == "before-rename":
        assert marker.exists()
        assert guest.inspect()["marker"] == ATTEMPT
        staged = guest.staged_fixture_receipt(marker.read_bytes())
        assert staged is not None
        assert staged["attempt"] == "2" * 32
        prior = json.loads(recovery_path.read_bytes())
        assert prior["state"] == "running"
        assert prior["phase"] == "verified-blocked"
        assert prior["interlock_retained"] is True
        monkeypatch.setattr(guest.os, "replace", replace)
        resumed = guest.recover_fixture(ATTEMPT, "3" * 32, payload(fixture_public_files("revised")))
        assert resumed["state"] == "succeeded", resumed
        assert not marker.exists()
        assert json.loads(recovery_path.read_bytes()) == prior
    else:
        assert not marker.exists()
        durable = guest.staged_fixture_receipt(recovery_path.read_bytes())
        assert durable is not None
        assert durable["state"] == "succeeded"
        assert durable["attempt"] == "2" * 32
        assert durable["original_attempt"] == ATTEMPT
        assert durable["interlock_retained"] is False
    fixture_installation[2].assert_not_called()


@pytest.mark.parametrize("fault", ["directory-sync", "final-receipt-corrupt"])
def test_fixture_recovery_restores_original_marker_when_atomic_completion_cannot_be_confirmed(
    installed, fixture_installation, retained_fixture, monkeypatch, fault,
):
    root, _source, _state = installed
    marker = root / ".deploying"
    recovery_path = root / "deployments" / ("2" * 32 + "-fixture-recovery.json")
    if fault == "directory-sync":
        sync = guest.sync_directory
        failed = False
        def fail_release_sync(directory):
            nonlocal failed
            if directory == root and not marker.exists() and not failed:
                failed = True
                raise OSError("private directory sync details")
            sync(directory)
        monkeypatch.setattr(guest, "sync_directory", fail_release_sync)
    else:
        replace = guest.os.replace
        def corrupt_final_receipt(source, destination):
            replace(source, destination)
            if source == marker and destination == recovery_path:
                envelope = json.loads(recovery_path.read_bytes())
                envelope["receipt_sha256"] = "0" * 64
                recovery_path.write_text(json.dumps(envelope))
        monkeypatch.setattr(guest.os, "replace", corrupt_final_receipt)
    result = guest.recover_fixture(ATTEMPT, "2" * 32, payload(fixture_public_files("revised")))
    assert result["state"] == "uncertain", result
    assert result["interlock_retained"] is True
    assert result["marker_conflict"] is False
    assert marker.read_text() == ATTEMPT
    assert json.loads(recovery_path.read_bytes())["state"] == "uncertain"
    assert "private" not in json.dumps(result)
    fixture_installation[2].assert_not_called()


def test_resumed_fixture_recovery_restores_exact_staged_marker_after_completion_failure(
    installed, fixture_installation, retained_fixture, monkeypatch,
):
    root, _source, _state = installed
    marker = root / ".deploying"
    recovery_path = root / "deployments" / ("2" * 32 + "-fixture-recovery.json")
    replace = guest.os.replace

    def interrupt_before_rename(source, destination):
        if source == marker and destination == recovery_path:
            raise SystemExit("simulated hard process termination")
        replace(source, destination)

    monkeypatch.setattr(guest.os, "replace", interrupt_before_rename)
    with pytest.raises(SystemExit, match="hard process termination"):
        guest.recover_fixture(ATTEMPT, "2" * 32, payload(fixture_public_files("revised")))
    staged_marker = marker.read_bytes()
    staged = guest.staged_fixture_receipt(staged_marker)
    assert staged is not None
    assert staged["attempt"] == "2" * 32

    monkeypatch.setattr(guest.os, "replace", replace)
    sync = guest.sync_directory
    failed = False

    def fail_release_sync(directory):
        nonlocal failed
        if directory == root and not marker.exists() and not failed:
            failed = True
            raise OSError("private directory sync details")
        sync(directory)

    monkeypatch.setattr(guest, "sync_directory", fail_release_sync)
    result = guest.recover_fixture(
        ATTEMPT, "3" * 32, payload(fixture_public_files("revised")),
    )

    assert result["state"] == "uncertain", result
    assert result["interlock_retained"] is True
    assert result["marker_conflict"] is False
    assert failed is True
    assert marker.read_bytes() == staged_marker
    assert guest.inspect()["marker"] == ATTEMPT
    fixture_installation[2].assert_not_called()


@pytest.mark.parametrize("fault", ["extra-field", "digest", "original-attempt", "final-state", "nested-extra"])
def test_inspect_rejects_arbitrary_json_in_recovery_marker(
    installed, fixture_installation, retained_fixture, monkeypatch, fault,
):
    root, _source, _state = installed
    marker = root / ".deploying"
    recovery_path = root / "deployments" / ("2" * 32 + "-fixture-recovery.json")
    replace = guest.os.replace
    def stop_before_release(source, destination):
        if source == marker and destination == recovery_path:
            raise SystemExit()
        replace(source, destination)
    monkeypatch.setattr(guest.os, "replace", stop_before_release)
    with pytest.raises(SystemExit):
        guest.recover_fixture(ATTEMPT, "2" * 32, payload(fixture_public_files("revised")))
    envelope = json.loads(marker.read_bytes())
    if fault == "extra-field":
        envelope["arbitrary"] = True
    elif fault == "digest":
        envelope["receipt_sha256"] = "0" * 64
    elif fault == "original-attempt":
        envelope["original_attempt"] = "3" * 32
    else:
        if fault == "final-state":
            envelope["final_receipt"]["state"] = "running"
        else:
            envelope["final_receipt"]["private_data"] = "arbitrary"
        encoded = json.dumps(envelope["final_receipt"], sort_keys=True, separators=(",", ":")).encode()
        envelope["receipt_sha256"] = hashlib.sha256(encoded).hexdigest()
    marker.write_text(json.dumps(envelope))
    assert guest.staged_fixture_receipt(marker.read_bytes()) is None
    assert guest.inspect()["marker"] == "unrecognized"


@pytest.mark.parametrize("active", [False, True])
def test_fixture_recovery_checks_fixed_inactive_services_when_health_is_unavailable(
    installed, fixture_installation, retained_fixture, monkeypatch, active,
):
    root, _source, state = installed
    health = guest.profile_health
    def stopped_health(config, port):
        if not state["calls"]:
            raise OSError("services stopped")
        return health(config, port)
    monkeypatch.setattr(guest, "profile_health", stopped_health)
    check = Mock(return_value=subprocess.CompletedProcess([], 0, b"inactive\nactive\n" if active else b"inactive\ninactive\n", b""))
    monkeypatch.setattr(guest.subprocess, "run", check)
    result = guest.recover_fixture(ATTEMPT, "2" * 32, payload(fixture_public_files("revised")))
    assert result["state"] == ("uncertain" if active else "succeeded"), result
    assert (root / ".deploying").exists() is active
    assert check.call_args.args[0] == ["/usr/bin/systemctl", "show", "--property=ActiveState", "--value", *guest.SERVICES]
    fixture_installation[2].assert_not_called()


def test_host_fixture_recovery_uses_only_fixed_action_and_linked_attempt(
    installed, fixture_installation, retained_fixture, checkout, monkeypatch,
):
    client = LocalGuestClient()
    files = fixture_public_files("revised")
    for source, name in zip(deploy.FIXTURE_SOURCES, guest.FIXTURE_FILES, strict=True):
        (checkout / source).write_bytes(files[name])
    monkeypatch.setattr(deploy, "ProxmoxClient", lambda: client)
    assert deploy.recover_runner_fixture(checkout, deploy.RunnerAdapter.neri_runner_v1, ATTEMPT) == 0
    assert [command[3] for command in client.commands] == ["inspect", "recover-fixture"]
    command = client.commands[1]
    assert command[4] == ATTEMPT
    assert command[5] != ATTEMPT and len(command[5]) == 32
    assert guest.decode_payload(command[6]) == payload(files)
    record = json.loads(next((checkout / ".dev-tools/runner-deployments").glob("*.json")).read_bytes())
    assert record["operation"] == "recover-fixture"
    assert record["original_attempt"] == ATTEMPT
    assert record["guest"]["attempt"] == record["attempt"]
    assert record["guest"]["original_attempt"] == ATTEMPT
    assert record["state"] == "succeeded"
    assert "private" not in json.dumps(record)
    fixture_installation[2].assert_not_called()


def test_host_fixture_recovery_refuses_wrong_marker_without_mutating_guest(checkout, monkeypatch):
    client = LocalGuestClient()
    monkeypatch.setattr(deploy, "ProxmoxClient", lambda: client)
    assert deploy.recover_runner_fixture(checkout, deploy.RunnerAdapter.neri_runner_v1, ATTEMPT) == 1
    assert [command[3] for command in client.commands] == ["inspect"]


def test_host_fixture_recovery_validates_public_payload_before_guest_submission(checkout, monkeypatch):
    (checkout / "scripts/lab-vm/wordpress-fixture/seed.sh").write_bytes(b"invalid control bytes")
    client = Mock()
    monkeypatch.setattr(deploy, "ProxmoxClient", client)
    assert deploy.recover_runner_fixture(checkout, deploy.RunnerAdapter.neri_runner_v1, ATTEMPT) == 1
    client.assert_not_called()


@pytest.mark.parametrize("state,code", [("succeeded", 0), ("uncertain", 1)])
def test_guest_main_dispatches_only_fixed_fixture_recovery_arguments(monkeypatch, capsys, state, code):
    value = payload(fixture_public_files("revised"))
    recover = Mock(return_value={"state": state})
    monkeypatch.setattr(guest, "recover_fixture", recover)
    monkeypatch.setattr(guest.sys, "argv", ["fixed-guest", "recover-fixture", ATTEMPT, "2" * 32, guest.encode_payload(value)])
    assert guest.main() == code
    recover.assert_called_once_with(ATTEMPT, "2" * 32, value)
    assert json.loads(capsys.readouterr().out) == {"state": state}


@pytest.mark.parametrize("fault", ["original-attempt", "receipt-link", "backup-link", "verified", "transport"])
def test_host_fixture_recovery_rejects_incomplete_receipt_without_retry(
    installed, fixture_installation, retained_fixture, checkout, monkeypatch, fault,
):
    client = LocalGuestClient()
    execute = client.agent_exec
    def incomplete(vmid, command):
        response = execute(vmid, command)
        if command[3] == "recover-fixture":
            if fault == "transport":
                raise ProxmoxError("private transport output")
            status = client.results[response["pid"]]
            record = json.loads(status["out-data"])
            if fault == "original-attempt":
                record["original_attempt"] = "3" * 32
            elif fault == "receipt-link":
                record["original_receipt"]["path"] = "/arbitrary"
            elif fault == "backup-link":
                record["original_backup"] = "/arbitrary"
            else:
                record["verified"] = False
            status["out-data"] = json.dumps(record)
        return response
    monkeypatch.setattr(client, "agent_exec", incomplete)
    monkeypatch.setattr(deploy, "ProxmoxClient", lambda: client)
    assert deploy.recover_runner_fixture(checkout, deploy.RunnerAdapter.neri_runner_v1, ATTEMPT) == 1
    assert [command[3] for command in client.commands] == ["inspect", "recover-fixture"]
    record = json.loads(next((checkout / ".dev-tools/runner-deployments").glob("*.json")).read_bytes())
    assert record["state"] == "uncertain"
    assert "private" not in json.dumps(record)
    fixture_installation[2].assert_not_called()


@pytest.mark.parametrize("fault", ["lock", "existing-receipt"])
def test_fixture_recovery_preserves_receipts_when_lock_or_attempt_is_unavailable(
    installed, fixture_installation, retained_fixture, fault,
):
    root, _source, state = installed
    recovery_path = root / "deployments" / ("2" * 32 + "-fixture-recovery.json")
    recovery_bytes = b'{"state":"running","owner":"original-recovery"}\n'
    if fault == "existing-receipt":
        recovery_path.write_bytes(recovery_bytes)
    with (root / ".deployment-lock").open("a") as lock:
        if fault == "lock":
            guest.fcntl.flock(lock, guest.fcntl.LOCK_EX | guest.fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError if fault == "lock" else guest.DeploymentError):
            guest.recover_fixture(ATTEMPT, "2" * 32, payload(fixture_public_files("revised")))
    if fault == "existing-receipt":
        assert recovery_path.read_bytes() == recovery_bytes
    else:
        assert not recovery_path.exists()
    assert (root / ".deploying").read_text() == ATTEMPT
    assert state["calls"] == []
    fixture_installation[2].assert_not_called()
    fixture_installation[3].assert_not_called()


def test_recovery_cli_preview_binds_exact_original_attempt(checkout, monkeypatch):
    project = service_ops.ProjectServices(
        project_id="neri", root=checkout, backend_service="backend", frontend_service="frontend",
        default_workers=(), optional_workers=(), backend_port=1, frontend_port=2,
        backend_dir=checkout / "backend", frontend_dir=checkout / "frontend", health_endpoint="/health",
        runner_adapter=deploy.RunnerAdapter.neri_runner_v1,
    )
    monkeypatch.setattr(service, "_load", lambda _: project)
    operation = Mock(return_value=0)
    monkeypatch.setattr(service, "recover_runner_fixture", operation)
    runner = CliRunner()
    preview = runner.invoke(service.app, ["recover-runner-fixture", "neri", ATTEMPT])
    assert preview.exit_code == 0, preview.output
    assert "RECOVER RUNNER FIXTURE" in preview.output
    assert ATTEMPT in preview.output
    operation.assert_not_called()
    token = preview.output.split("--confirm ", 1)[1].strip()
    wrong = runner.invoke(service.app, ["recover-runner-fixture", "neri", "3" * 32, "--confirm", token])
    assert wrong.exit_code == 1, wrong.output
    operation.assert_not_called()
    result = runner.invoke(service.app, ["recover-runner-fixture", "neri", ATTEMPT, "--confirm", token])
    assert result.exit_code == 0, result.output
    operation.assert_called_once_with(checkout, deploy.RunnerAdapter.neri_runner_v1, ATTEMPT)
    invalid = runner.invoke(service.app, ["recover-runner-fixture", "neri", "not-an-attempt"])
    assert invalid.exit_code == 1, invalid.output
