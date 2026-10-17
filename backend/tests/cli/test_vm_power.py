"""st vm power operations report what PVE actually did."""

import json
import subprocess

import httpx
import pytest

from cli.lib import proxmox
from cli.lib.proxmox import ProxmoxClient, ProxmoxConfig, ProxmoxError


@pytest.fixture(autouse=True)
def no_host_registry(monkeypatch, tmp_path):
    monkeypatch.setattr(proxmox, "NIGHTSHIFT_REGISTRY", tmp_path / "missing.json")


def client() -> ProxmoxClient:
    return ProxmoxClient(ProxmoxConfig("https://fixture", "id", "secret", "node"))


@pytest.mark.parametrize("action", ["start", "stop"])
def test_power_waits_for_the_task_and_surfaces_its_failure(monkeypatch, action):
    # PVE accepts a start of a running VM and fails only its task; "starting" was printed regardless.
    pve = client()
    monkeypatch.setattr(pve, "request", lambda method, path, **_: f"UPID:{path}")
    waited = []

    def wait_task(upid, **_):
        waited.append(upid)
        raise ProxmoxError("Proxmox task failed: VM 120 already running")

    monkeypatch.setattr(pve, "wait_task", wait_task)
    with pytest.raises(ProxmoxError, match="already running"):
        getattr(pve, action)("120")
    assert waited == [f"UPID:/nodes/node/qemu/120/status/{action}"]


def test_permission_403_names_the_pools_that_grant_vm_rights(monkeypatch):
    monkeypatch.setattr(proxmox, "_tls_context", lambda _: None)
    body = '{"message":"Permission check failed (/vms/120, VM.PowerMgmt)\\n","data":null}'
    monkeypatch.setattr(proxmox.httpx, "request", lambda *a, **k: httpx.Response(403, text=body))
    with pytest.raises(ProxmoxError) as failure:
        client().start("120")
    message = str(failure.value)
    assert "/vms/120, VM.PowerMgmt" in message
    assert "'summitflow'" in message and f"'{proxmox.POWER_POOL}'" in message


def write_registry(path, rows):
    path.write_text(json.dumps({"findings": [{"code": "assets.registry", "details": {"assets": rows}}]}))


def test_reserved_lab_asset_follows_the_nightshift_registry(tmp_path):
    reg = tmp_path / "registry.json"
    write_registry(reg, [
        {"id": "ominull-target-linux", "vmid": 112, "presence": "parked", "tier": "lab", "kind": "vm"},
        {"id": "neri-lab", "vmid": 120, "presence": "intermittent", "tier": "lab", "kind": "vm"},
        {"id": "st-browser", "vmid": 100, "presence": "always_on", "tier": "standard", "kind": "vm"},
        {"id": "ubuntu-2404-cloud", "vmid": 9000, "presence": "parked", "tier": "lab", "kind": "template"},
    ])
    assert proxmox.reserved_lab_asset("112", reg) == "ominull-target-linux"
    assert proxmox.reserved_lab_asset("120", reg) == "neri-lab"
    assert proxmox.reserved_lab_asset("100", reg) is None
    assert proxmox.reserved_lab_asset("9000", reg) is None
    assert proxmox.reserved_lab_asset("112", tmp_path / "missing.json") is None


def test_start_declares_a_parked_vm_after_starting_it(monkeypatch, tmp_path):
    reg = tmp_path / "registry.json"
    write_registry(reg, [{"id": "ominull-target-linux", "vmid": 112, "presence": "parked", "tier": "lab", "kind": "vm"}])
    monkeypatch.setattr(proxmox, "NIGHTSHIFT_REGISTRY", reg)
    calls = []
    monkeypatch.setattr(proxmox.subprocess, "run", lambda cmd, **_: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "declared\n", ""))
    pve = client()
    monkeypatch.setattr(pve, "request", lambda method, path, **_: calls.append(path) or "UPID:x")
    monkeypatch.setattr(pve, "wait_task", lambda upid, **_: None)
    pve.start("112", lab_hours=2, lab_reason="pentest run")
    assert calls == [
        "/nodes/node/qemu/112/status/start",
        ["nightshift", "lab-use", "start", "ominull-target-linux", "--hours", "2", "--reason", "pentest run"],
    ]
    pve.start("100")  # not in the registry: no declaration
    assert calls[-1] == "/nodes/node/qemu/100/status/start" and len(calls) == 3


def test_start_fails_open_when_nightshift_is_unavailable(monkeypatch, tmp_path, capsys):
    reg = tmp_path / "registry.json"
    write_registry(reg, [{"id": "neri-lab", "vmid": 120, "presence": "intermittent", "tier": "lab", "kind": "vm"}])
    monkeypatch.setattr(proxmox, "NIGHTSHIFT_REGISTRY", reg)

    def missing(cmd, **_):
        raise FileNotFoundError("nightshift")

    monkeypatch.setattr(proxmox.subprocess, "run", missing)
    pve = client()
    started = []
    monkeypatch.setattr(pve, "request", lambda method, path, **_: started.append(path) or "UPID:x")
    monkeypatch.setattr(pve, "wait_task", lambda upid, **_: None)
    pve.start("120")
    assert started == ["/nodes/node/qemu/120/status/start"]
    assert "could not declare lab use of neri-lab" in capsys.readouterr().err


@pytest.mark.parametrize("failure", ["Proxmox task failed: VM 112 already running", "Permission check failed (/vms/112, VM.PowerMgmt)"])
def test_failed_start_declares_nothing(monkeypatch, tmp_path, failure):
    # A refused start, or a VM someone else already runs, must not get a declaration naming this session.
    reg = tmp_path / "registry.json"
    write_registry(reg, [{"id": "ominull-target-linux", "vmid": 112, "presence": "parked", "tier": "lab", "kind": "vm"}])
    monkeypatch.setattr(proxmox, "NIGHTSHIFT_REGISTRY", reg)
    declared = []
    monkeypatch.setattr(proxmox.subprocess, "run", lambda cmd, **_: declared.append(cmd))
    pve = client()
    monkeypatch.setattr(pve, "request", lambda method, path, **_: "UPID:x")

    def fail(upid, **_):
        raise ProxmoxError(failure)

    monkeypatch.setattr(pve, "wait_task", fail)
    with pytest.raises(ProxmoxError):
        pve.start("112")
    assert declared == []
