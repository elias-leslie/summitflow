"""Managed clone success means a usable guest, not merely a completed copy."""

import base64
import json
import shlex
import struct
import subprocess
import sys
from urllib.parse import unquote

import pytest
from typer.testing import CliRunner

from cli.commands import vm
from cli.lib import vm_clone
from cli.lib.proxmox import ProxmoxClient, ProxmoxConfig, ProxmoxError, ProxmoxTaskError

REAL_LOAD_PROFILE = vm_clone.load_clone_access_profile


def public_key():
    kind = b"ssh-ed25519"
    blob = struct.pack(">I", len(kind)) + kind + struct.pack(">I", 32) + b"a" * 32
    return "ssh-ed25519 " + base64.b64encode(blob).decode()


@pytest.fixture(autouse=True)
def configured_profile(monkeypatch):
    monkeypatch.setattr(vm_clone, "load_clone_access_profile", lambda: vm_clone.CloneAccessProfile("9000", "operator", public_key(), timeout_seconds=3))
    clock = [0.0]
    monkeypatch.setattr(vm_clone.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(vm_clone.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))


class CopyOnlyClient:
    """The real failure pattern: copy succeeds, but guest access is absent."""

    def __init__(self):
        self.calls = []

    def clone(self, template, newid, name):
        self.calls.append("copy")
        return "UPID:copy-completed"

    def list_vms(self):
        return [{"vmid": 9000, "template": 1}]

    def config_get(self, vmid):
        if vmid == "9910":
            return {"name": "qualification", "ostype": "l26"}
        return {"template": 1, "ostype": "l26", "ide2": "local:cloudinit", "agent": "1", "net0": "virtio=02:00:00:00:00:01,bridge=vmbr0"}

    def config_update(self, vmid, data):
        self.calls.append(("configure", data))

    def start(self, vmid):
        self.calls.append("start")

    def agent_exec(self, vmid, command):
        raise ProxmoxError("QEMU guest agent is not running")


def test_copy_complete_without_access_or_agent_is_not_ready(monkeypatch):
    monkeypatch.setattr(vm, "_client", lambda: CopyOnlyClient())
    result = CliRunner().invoke(vm.app, ["clone", "9000", "9910", "qualification"])
    assert result.exit_code != 0, result.output
    assert "Done: VM 9910" not in result.output
    assert "phase=readiness" in result.output
    assert "UPID:copy-completed" in result.output
    assert "VM 9910 retained" in result.output
    assert "Guest ready:" not in result.output


class ReadyClient(CopyOnlyClient):
    def agent_exec(self, vmid, command):
        self.calls.append(("exec", command))
        return {"pid": 7}

    def agent_exec_status(self, vmid, pid):
        return {"exited": True, "exitcode": 0}

    def ip_addresses(self, vmid):
        return ["127.0.0.2", "169.254.1.1", "0.0.0.0", "224.0.0.1", "10.0.4.91"]


def invoke(monkeypatch, client, *extra):
    monkeypatch.setattr(vm, "_client", lambda: client)
    return CliRunner().invoke(vm.app, ["clone", "9000", "9910", "qualification", *extra])


def test_normal_clone_configures_public_access_before_boot_and_proves_ready(monkeypatch):
    client = ReadyClient()
    result = invoke(monkeypatch, client)
    assert result.exit_code == 0, result.output
    assert client.calls[0] == "copy"
    assert client.calls[1][0] == "configure"
    access = client.calls[1][1]
    assert access["ciuser"] == "operator"
    assert unquote(access["sshkeys"]) == public_key()
    assert access["ipconfig0"] == "ip=dhcp"
    assert access["delete"] == "cipassword"
    assert client.calls[2] == "start"
    assert client.calls[3][0] == "exec"
    assert "hostname -s" in client.calls[3][1][2]
    assert "cloud-init status --wait" in client.calls[3][1][2]
    assert "Guest ready: VM 9910 IPv4=10.0.4.91" in result.output
    assert result.output.index("Copy complete") < result.output.index("Guest ready")
    assert public_key() not in result.output


def test_clone_only_preserves_windows_copy_without_claiming_ready(monkeypatch):
    client = CopyOnlyClient()
    result = invoke(monkeypatch, client, "--clone-only")
    assert result.exit_code == 0, result.output
    assert client.calls == ["copy"]
    assert "COPY ONLY" in result.output
    assert "guest NOT provisioned, started, or ready" in result.output


@pytest.mark.parametrize("change,reason", [
    ({"ostype": "win11"}, "Linux template"),
    ({"template": 0}, "Linux template"),
    ({"ide2": "local:cdrom"}, "cloud-init drive"),
    ({"cicustom": "user=local:snippets/custom.yaml"}, "override owner access"),
])
def test_unsupported_template_fails_before_allocation(monkeypatch, change, reason):
    client = ReadyClient()
    original = client.config_get
    monkeypatch.setattr(client, "config_get", lambda vmid: original(vmid) | change)
    result = invoke(monkeypatch, client)
    assert result.exit_code != 0
    assert "phase=preflight" in result.output
    assert reason in result.output
    assert client.calls == []


def test_existing_id_fails_before_allocation(monkeypatch):
    client = ReadyClient()
    monkeypatch.setattr(client, "list_vms", lambda: [{"vmid": 9910}])
    result = invoke(monkeypatch, client)
    assert "already exists" in result.output
    assert client.calls == []


def test_unqualified_template_fails_before_allocation(monkeypatch):
    monkeypatch.setattr(vm_clone, "load_clone_access_profile", lambda: vm_clone.CloneAccessProfile("9001", "operator", public_key()))
    client = ReadyClient()
    result = invoke(monkeypatch, client)
    assert "qualified PROXMOX_CLONE_TEMPLATE" in result.output
    assert client.calls == []


def test_wrong_destination_identity_is_retained_without_boot(monkeypatch):
    client = ReadyClient()
    original = client.config_get
    monkeypatch.setattr(client, "config_get", lambda vmid: {"name": "wrong"} if vmid == "9910" else original(vmid))
    result = invoke(monkeypatch, client)
    assert "phase=configure" in result.output
    assert "UPID:copy-completed" in result.output
    assert client.calls == ["copy"]


def test_configure_failure_does_not_boot_or_echo_key(monkeypatch):
    client = ReadyClient()
    def fail(*args):
        raise ProxmoxError("reflected " + public_key())
    monkeypatch.setattr(client, "config_update", fail)
    result = invoke(monkeypatch, client)
    assert result.exit_code != 0
    assert "phase=configure" in result.output
    assert public_key() not in result.output
    assert client.calls == ["copy"]


def test_wrong_guest_identity_is_not_ready(monkeypatch):
    client = ReadyClient()
    monkeypatch.setattr(client, "agent_exec_status", lambda *_: {"exited": True, "exitcode": 1})
    result = invoke(monkeypatch, client)
    assert result.exit_code != 0
    assert "qualification failed" in result.output
    assert "Guest ready:" not in result.output


def test_agent_without_usable_address_times_out(monkeypatch):
    client = ReadyClient()
    monkeypatch.setattr(client, "ip_addresses", lambda _: ["127.0.0.2", "169.254.1.1", "not-an-ip"])
    result = invoke(monkeypatch, client)
    assert result.exit_code != 0
    assert "phase=readiness" in result.output
    assert "Timed out" in result.output


def test_low_level_copy_returns_task_and_failure_retains_it(monkeypatch):
    client = ProxmoxClient(ProxmoxConfig("https://fixture", "id", "secret", "node"))
    monkeypatch.setattr(client, "request", lambda *args, **kwargs: "UPID:retained")
    monkeypatch.setattr(client, "wait_task", lambda *args, **kwargs: None)
    assert client.clone("9000", "9910", "qualification") == "UPID:retained"
    def fail(*args, **kwargs):
        raise ProxmoxError("timeout")
    monkeypatch.setattr(client, "wait_task", fail)
    with pytest.raises(ProxmoxTaskError) as failure:
        client.clone("9000", "9910", "qualification")
    assert failure.value.upid == "UPID:retained"


@pytest.mark.parametrize("text", ["PRIVATE KEY material is not public", "ssh-ed25519 not-base64", "ssh-ed25519 AAAA", ""])
def test_private_or_malformed_public_key_never_passes(text, tmp_path):
    path = tmp_path / "key.pub"
    path.write_text(text)
    with pytest.raises(ProxmoxError, match="valid public SSH keys") as failure:
        vm_clone._public_keys(path)
    assert text not in str(failure.value) if text else True


def test_owner_profile_missing_key_fails_before_allocation(monkeypatch):
    def missing():
        raise ProxmoxError("Configure PROXMOX_CLONE_PUBLIC_KEY_FILE explicitly")
    monkeypatch.setattr(vm_clone, "load_clone_access_profile", missing)
    client = ReadyClient()
    result = invoke(monkeypatch, client)
    assert result.exit_code != 0
    assert "phase=preflight" in result.output
    assert client.calls == []


def test_any_template_is_protected_from_destroy(monkeypatch):
    client = ProxmoxClient(ProxmoxConfig("https://fixture", "id", "secret", "node"))
    monkeypatch.setattr(client, "config_get", lambda _: {"template": 1})
    with pytest.raises(ProxmoxError, match="Cannot destroy template VM 9001"):
        client.destroy("9001")


@pytest.mark.parametrize("state,ready", [
    ({"status": "done", "errors": [], "recoverable_errors": {}}, True),
    ({"status": "done", "errors": [], "recoverable_errors": {"DEPRECATED": ["user schema"]}}, True),
    ({"status": "done", "errors": ["access provisioning failed"], "recoverable_errors": {}}, False),
    ({"status": "done", "errors": [], "recoverable_errors": {"WARNING": ["access warning"]}}, False),
    ({"status": "running", "errors": [], "recoverable_errors": {}}, False),
])
def test_cloud_init_probe_accepts_only_done_without_provisioning_errors(monkeypatch, state, ready):
    client = ReadyClient()
    def execution_status(*_):
        probe = client.calls[-1][1][2]
        parser = shlex.split(probe)[-1]
        executed = subprocess.run([sys.executable, "-c", parser], input=json.dumps(state), text=True, capture_output=True)
        return {"exited": True, "exitcode": executed.returncode}
    monkeypatch.setattr(client, "agent_exec_status", execution_status)
    result = invoke(monkeypatch, client)
    assert (result.exit_code == 0) is ready, result.output


@pytest.mark.parametrize("override", [
    {"PROXMOX_CLONE_USER": "root"},
    {"PROXMOX_CLONE_READY_TIMEOUT": "nan"},
    {"PROXMOX_CLONE_READY_TIMEOUT": "0"},
    {"PROXMOX_CLONE_IPCONFIG0": "ip=10.0.4.50/24,gw=10.0.5.1"},
    {"PROXMOX_CLONE_PUBLIC_KEY_FILE": "/nonexistent/owner.pub"},
])
def test_bad_owner_configuration_is_rejected(monkeypatch, tmp_path, override):
    path = tmp_path / "owner.pub"
    path.write_text(public_key())
    values = {"PROXMOX_CLONE_TEMPLATE": "9000", "PROXMOX_CLONE_USER": "operator", "PROXMOX_CLONE_PUBLIC_KEY_FILE": str(path)} | override
    for key in values:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(vm_clone, "_read_env_file", lambda _: values)
    with pytest.raises(ProxmoxError):
        REAL_LOAD_PROFILE()


def test_copy_failure_retains_task_identity_at_cli(monkeypatch):
    client = ReadyClient()
    def fail(*_):
        raise ProxmoxTaskError("UPID:failed-copy")
    monkeypatch.setattr(client, "clone", fail)
    result = invoke(monkeypatch, client)
    assert result.exit_code != 0
    assert "phase=copy task=UPID:failed-copy" in result.output
    assert "VM 9910 retained" in result.output
    assert client.calls == []


def test_start_failure_retains_configured_vm(monkeypatch):
    client = ReadyClient()
    def fail(*_):
        raise ProxmoxError("start failed")
    monkeypatch.setattr(client, "start", fail)
    result = invoke(monkeypatch, client)
    assert result.exit_code != 0
    assert "phase=start task=UPID:copy-completed" in result.output
    assert client.calls[1][0] == "configure"
    assert len(client.calls) == 2
