"""Scoped service access preserves isolation and closes only its own SSH processes."""

import json
import subprocess
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from cli.commands import vm
from cli.lib import vm_forward as vf
from cli.lib.proxmox import ProxmoxError


class Guests:
    def __init__(self):
        self.rows = [
            {"vmid": 125, "name": "workbench", "type": "qemu", "status": "running", "pool": "summitflow"},
            {"vmid": 100, "name": "browser", "type": "qemu", "status": "running", "pool": "summitflow"},
        ]
        self.cfg: dict[str, object] = {"name": "workbench", "net0": "virtio=AA:BB:CC:DD:EE:FF,bridge=labnet,firewall=1"}
        self.config: SimpleNamespace | None = None

    def list_vms(self):
        return self.rows

    def config_get(self, vmid):
        return self.cfg if vmid == "125" else {"name": "browser"}

    def ip_addresses(self, vmid):
        return ["10.20.0.112"] if vmid == "125" else ["192.168.86.234"]


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize("change", ["pool", "template", "stopped", "address"])
def test_refuses_non_lab_or_non_running_sources(runtime, monkeypatch, change):
    guests = Guests()
    if change == "pool":
        guests.rows[0]["pool"] = "production"
    elif change == "template":
        guests.cfg["template"] = 1
    elif change == "stopped":
        guests.rows[0]["status"] = "stopped"
    else:
        monkeypatch.setattr(guests, "ip_addresses", lambda _: ["192.168.86.1"])
    monkeypatch.setattr(vf, "_start", lambda *a, **k: pytest.fail("must refuse before opening SSH"))
    with pytest.raises(ProxmoxError):
        vf.forward(guests, "125", 8080)


def test_lab_subnets_come_from_the_proxmox_config(runtime, monkeypatch):
    guests = Guests()
    guests.config = SimpleNamespace(pool="summitflow", lab_cidrs="10.30.0.0/24")
    monkeypatch.setattr(vf, "_start", lambda *a, **k: pytest.fail("must refuse before opening SSH"))
    with pytest.raises(ProxmoxError, match="no usable labnet"):
        vf.forward(guests, "125", 8080)
    guests.config = SimpleNamespace(pool="summitflow", lab_cidrs="not-a-subnet")
    with pytest.raises(ProxmoxError, match="PROXMOX_LAB_CIDRS"):
        vf.forward(guests, "125", 8080)


def test_local_destination_reuse_and_exact_cleanup(runtime, monkeypatch):
    started, stopped = [], []
    monkeypatch.setattr(vf, "_verify", lambda *a: None)
    monkeypatch.setattr(vf, "_free_port", lambda: 18080)
    monkeypatch.setattr(vf, "_remote", lambda *a: "28080")
    monkeypatch.setattr(vf, "_owned", lambda p: True)
    monkeypatch.setattr(vf, "_stop", stopped.append)

    def start(host, spec, **kwargs):
        started.append((host, spec, kwargs))
        return {"pid": len(started), "start_token": "proof", "argv": ["ssh"]}

    monkeypatch.setattr(vf, "_start", start)
    first = vf.forward(Guests(), "125", 8080, "100")
    assert first["local_url"] == "http://127.0.0.1:18080"
    assert first["destination_url"] == "http://127.0.0.1:28080"
    assert started[0][:2] == ("10.20.0.112", "127.0.0.1:18080:10.20.0.112:8080")
    assert started[1][:2] == ("192.168.86.234", "127.0.0.1:28080:127.0.0.1:18080")
    assert started[1][2]["reverse"] is True
    again = vf.forward(Guests(), "125", 8080, "100")
    assert again["reused"] and len(started) == 2
    assert vf.close(first["id"])["closed"]
    assert stopped == list(reversed(first["processes"]))
    assert not vf.close(first["id"])["closed"]


def test_destination_failure_cleans_started_source(runtime, monkeypatch):
    stopped = []
    monkeypatch.setattr(vf, "_verify", lambda *a: None)
    monkeypatch.setattr(vf, "_remote", lambda *a: "invalid-port")
    monkeypatch.setattr(vf, "_start", lambda *a, **k: {"pid": 7})
    monkeypatch.setattr(vf, "_stop", stopped.append)
    with pytest.raises(ProxmoxError, match="valid loopback port"):
        vf.forward(Guests(), "125", 8080, "100")
    assert stopped == [{"pid": 7}]
    assert not list(vf._runtime().glob("*.json"))


def test_observed_dead_transport_replaced_once(runtime, monkeypatch):
    started, stopped = [], []
    monkeypatch.setattr(vf, "_verify", lambda *a: None)
    monkeypatch.setattr(vf, "_owned", lambda p: False)
    monkeypatch.setattr(vf, "_stop", stopped.append)

    def start(*args, **kwargs):
        proof = {"pid": len(started) + 1, "start_token": "start", "argv": ["ssh"]}
        started.append(proof)
        return proof

    monkeypatch.setattr(vf, "_start", start)
    first = vf.forward(Guests(), "125", 8080)
    second = vf.forward(Guests(), "125", 8080)
    assert first["id"] == second["id"] and not second["reused"]
    assert len(started) == 2 and stopped == first["processes"]


def test_source_failure_starts_no_destination_or_metadata(runtime, monkeypatch):
    monkeypatch.setattr(vf, "_verify", lambda *a: None)
    calls = []

    def fail(*args, **kwargs):
        calls.append(args)
        raise ProxmoxError("observed SSH failure")

    monkeypatch.setattr(vf, "_start", fail)
    with pytest.raises(ProxmoxError, match="observed SSH failure"):
        vf.forward(Guests(), "125", 8080, "100")
    assert len(calls) == 1
    assert not list(vf._runtime().glob("*.json"))


def test_stop_does_not_signal_reused_pid(monkeypatch):
    monkeypatch.setattr(vf, "_process", lambda _: {"pid": 7, "start_token": "new", "argv": ["ssh"]})
    monkeypatch.setattr(vf.os, "kill", lambda *a: pytest.fail("reused PID must not be signalled"))
    vf._stop({"pid": 7, "start_token": "old", "argv": ["ssh"]})


def test_process_proof_reads_real_owned_child():
    child = subprocess.Popen(["sleep", "30"])
    try:
        proof = vf._process(child.pid)
        assert proof and proof["pid"] == child.pid
        assert vf._owned(proof)
        vf._stop(proof)
        child.wait(timeout=3)
        assert not vf._owned(proof)
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=3)


def test_ssh_override_is_specific_and_loopback_only(runtime, monkeypatch):
    captured = []
    process = {"pid": 7, "start_token": "start", "argv": []}

    def popen(args, **kwargs):
        captured.extend(args)
        process["argv"] = args
        control = args[args.index("-S") + 1]
        from pathlib import Path
        Path(control).touch()
        return SimpleNamespace(pid=7, poll=lambda: None)

    monkeypatch.setattr(vf.subprocess, "Popen", popen)
    monkeypatch.setattr(vf.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(vf, "_process", lambda _: process)
    vf._start("10.20.0.112", "127.0.0.1:18080:10.20.0.112:8080", reverse=False, control=runtime / "control")
    assert "ClearAllForwardings=no" in captured
    assert "ForwardAgent=no" in captured and "ForwardX11=no" in captured
    assert "ExitOnForwardFailure=yes" in captured
    assert captured[-1] == "10.20.0.112"
    assert "-L" in captured and "-R" not in captured


def test_cli_json_contract(monkeypatch):
    monkeypatch.setattr(vm, "_client", lambda: Guests())
    monkeypatch.setattr(vf, "forward", lambda *a: {"id": "sample", "local_url": "http://127.0.0.1:1", "destination_url": None})
    result = CliRunner().invoke(vm.app, ["forward", "125", "8080", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["id"] == "sample"
    result = CliRunner().invoke(vm.app, ["forward-close", "../../outside", "--json"])
    assert result.exit_code == 1


def test_runtime_refuses_shared_directory(runtime):
    root = vf._runtime()
    root.chmod(0o755)
    with pytest.raises(ProxmoxError, match="private"):
        vf.close("a" * 24)
    root.chmod(0o700)


def test_guest_hostname_must_match(monkeypatch):
    monkeypatch.setattr(vf, "_remote", lambda *a: "other-guest")
    with pytest.raises(ProxmoxError, match="identity"):
        vf._verify("10.20.0.112", {"name": "workbench"})
