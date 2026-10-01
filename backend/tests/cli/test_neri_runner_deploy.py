"""Fixed runner deployment: real filesystem transactions, simulated guest services."""

import base64
import hashlib
import json
import os
import subprocess
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
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
    ):
        monkeypatch.setattr(guest, attribute, path)
        directory = path if attribute == "FIXTURE_ROOT" else path.parent
        directory.mkdir(exist_ok=True)
        directory.chmod(0o755)
    files = fixture_public_files()
    for name, path in guest.fixture_paths().items():
        path.write_bytes(files[name])
        path.chmod(0o755 if name.endswith(".sh") else 0o644)
    private = {"api_key": "private-api-key", "nested": {"keep": ["private-value"]},
               "target_artifact_identity": guest.fixture_contents(payload(files))[2]}
    guest.WORDPRESS_CONFIG.write_text(json.dumps(private))
    guest.WORDPRESS_CONFIG.chmod(0o640)
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
