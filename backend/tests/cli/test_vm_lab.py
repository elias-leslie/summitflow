"""Bounded lab observations and identity-guarded resets use only scoped PVE API calls."""

import json
import ssl
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from typer.testing import CliRunner

from cli.client import APIError
from cli.commands import vm
from cli.lib import proxmox
from cli.lib.proxmox import ProxmoxClient, ProxmoxConfig, ProxmoxError
from cli.lib.proxmox_remote import RemoteProxmoxClient


class Lab:
    def __init__(self, monkeypatch, *, running=False, ram=False):
        self.calls, self.waited = [], []
        self.running, self.ram, self.parent = running, ram, "other"
        self.config: dict[str, Any] = {"name": "lab-120"}
        self.status = {"vmid": 120, "name": "lab-120", "uptime": 7}
        self.snapshots = [{"name": "clean"}]
        self.snapshot_config = {"name": "lab-120"}
        self.capacity = {"active": 1, "enabled": 1, "total": 100, "used": 40, "avail": 60}
        self.permissions = {"/nodes/node": {"Sys.Audit": 0}}
        self.tasks: dict[str, Any] = {"qmstart": [{"id": "120", "type": "qmstart", "starttime": 10}], "qmrollback": []}
        self.overrides = {}
        self.client = ProxmoxClient(ProxmoxConfig("https://fixture", "id", "private-secret", "node"))
        monkeypatch.setattr(proxmox, "reserved_lab_asset", lambda vmid: "lab" if vmid in {"120", "121"} else None)
        monkeypatch.setattr(self.client, "request", self.request)
        monkeypatch.setattr(self.client, "wait_task", lambda upid, **kw: self.waited.append((upid, kw)))

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs.get("data")))
        if path in self.overrides:
            value = self.overrides[path]
            if isinstance(value, Exception):
                raise value
            return value
        if path.startswith("/access/permissions?"):
            return self.permissions
        if "/tasks?" in path:
            return self.tasks[parse_qs(urlsplit(path).query)["typefilter"][0]]
        if "/tasks/" in path:
            return {"status": "stopped", "exitstatus": "OK"}
        if "/storage/" in path:
            return self.capacity
        if path.endswith("/status/current"):
            return self.status | {"status": "running" if self.running else "stopped"}
        if path.endswith("/snapshot/clean/config"):
            return self.snapshot_config
        if path.endswith("/config"):
            return self.config
        if path.endswith("/snapshot"):
            return [*self.snapshots, {"name": "current", "parent": self.parent}]
        if method == "POST":
            if path.endswith("/rollback"):
                self.parent, self.running = "clean", self.ram
            elif path.endswith("/stop"):
                self.running = False
            return f"UPID:{len(self.calls)}"
        raise AssertionError((method, path))

    def reset(self):
        return self.client.reset("120", name="lab-120", snapshot="clean")


def test_observe_is_complete_scoped_and_returns_only_selected_evidence(monkeypatch):
    lab = Lab(monkeypatch)
    lab.tasks["qmstart"].append({"id": "120", "type": "qmstart", "starttime": 30, "user": "private-user"})
    result = lab.client.observe(["120"], "local-lvm")
    assert result == {
        "vms": [{"vmid": 120, "name": "lab-120", "status": "stopped", "uptime": 7, "lock": None,
                 "snapshots": ["clean"], "latest_tasks": {"qmstart": 30, "qmrollback": None}}],
        "storage": {"name": "local-lvm", "total": 100, "used": 40, "available": 60},
    }
    assert all(method == "GET" for method, _, _ in lab.calls)
    assert "private" not in json.dumps(result)
    tasks = [path for _, path, _ in lab.calls if "/tasks?" in path]
    assert len(tasks) == 2
    assert all("vmid=120" in path and "source=all" in path and "limit=1000" in path for path in tasks)


@pytest.mark.parametrize("ids,storage", [([], "local-lvm"), (["120"] * 2, "local-lvm"),
    ([str(i) for i in range(100, 133)], "local-lvm"), (["0120"], "local-lvm"), (["120/stop"], "local-lvm"),
    ([120], "local-lvm"), (["120"], "../other"), (["120"], "local?x=1"), ("120", "local-lvm")])
def test_observe_rejects_invalid_scope_before_requests(monkeypatch, ids, storage):
    lab = Lab(monkeypatch)
    with pytest.raises(ProxmoxError):
        lab.client.observe(ids, storage)
    assert lab.calls == []


@pytest.mark.parametrize("ids", [["150"], ["120", "150"]])
def test_observe_rejects_production_ids_before_any_task_or_api_query(monkeypatch, ids):
    lab = Lab(monkeypatch)
    with pytest.raises(ProxmoxError, match="registered Nightshift"):
        lab.client.observe(ids, "local-lvm")
    assert lab.calls == []


def test_reset_rejects_unregistered_vm_before_mutation(monkeypatch):
    lab = Lab(monkeypatch)
    with pytest.raises(ProxmoxError, match="registered Nightshift"):
        lab.client.reset("150", name="prod", snapshot="clean")
    assert lab.calls == []


def test_observe_refuses_silently_filtered_task_history(monkeypatch):
    lab = Lab(monkeypatch)
    lab.permissions = {"/nodes/node": {}}
    with pytest.raises(ProxmoxError, match=r"Sys\.Audit"):
        lab.client.observe(["120"], "local-lvm")
    assert not any("/tasks?" in path for _, path, _ in lab.calls)


@pytest.mark.parametrize("component", ["status", "config", "snapshots", "tasks", "capacity", "second-vm"])
def test_observe_refuses_incomplete_components(monkeypatch, component):
    lab = Lab(monkeypatch)
    if component == "status":
        del lab.status["uptime"]
    elif component == "config":
        lab.config = {}
    elif component == "snapshots":
        lab.overrides["/nodes/node/qemu/120/snapshot"] = None
    elif component == "tasks":
        lab.tasks["qmrollback"] = None
    elif component == "capacity":
        del lab.capacity["avail"]
    else:
        lab.overrides["/nodes/node/qemu/121/status/current"] = None
    with pytest.raises(ProxmoxError):
        lab.client.observe(["120", "121"] if component == "second-vm" else ["120"], "local-lvm")


@pytest.mark.parametrize("tasks", [[{"id": "150", "type": "qmstart", "starttime": 10}],
    [{"id": "120", "type": "qmrollback", "starttime": 10}], [{"id": "120", "type": "qmstart", "starttime": "10"}]])
def test_observe_refuses_wrong_or_malformed_task_evidence(monkeypatch, tasks):
    lab = Lab(monkeypatch)
    lab.tasks["qmstart"] = tasks
    with pytest.raises(ProxmoxError, match="history"):
        lab.client.observe(["120"], "local-lvm")


def test_observe_refuses_truncated_history(monkeypatch):
    lab = Lab(monkeypatch)
    lab.tasks["qmstart"] *= proxmox.LAB_TASK_LIMIT
    with pytest.raises(ProxmoxError, match="excessive"):
        lab.client.observe(["120"], "local-lvm")


@pytest.mark.parametrize("running,ram,stops", [(False, False, 0), (True, False, 1), (True, True, 2)])
def test_reset_waits_for_tasks_and_verifies_snapshot_and_stopped_state(monkeypatch, running, ram, stops):
    lab = Lab(monkeypatch, running=running, ram=ram)
    assert lab.reset() == {"vmid": 120, "name": "lab-120", "snapshot": "clean", "status": "stopped"}
    mutations = [(path, data) for method, path, data in lab.calls if method == "POST"]
    assert mutations.count(("/nodes/node/qemu/120/status/stop", None)) == stops
    assert ("/nodes/node/qemu/120/snapshot/clean/rollback", {"start": 0}) in mutations
    assert len(lab.waited) == stops + 1
    assert not lab.running and lab.parent == "clean"


@pytest.mark.parametrize("change", ["name", "lock", "template", "missing-snapshot", "snapshot-name", "incomplete-snapshot"])
def test_reset_guards_before_any_mutation(monkeypatch, change):
    lab = Lab(monkeypatch, running=True)
    if change == "name":
        lab.status["name"] = lab.config["name"] = "wrong"
    elif change == "snapshot-name":
        lab.snapshot_config["name"] = "wrong"
    elif change == "missing-snapshot":
        lab.snapshots = []
    elif change == "incomplete-snapshot":
        lab.snapshots[0]["snapstate"] = "prepare"
    else:
        lab.config[change] = "backup" if change == "lock" else 1
    with pytest.raises(ProxmoxError):
        lab.reset()
    assert not any(method == "POST" for method, _, _ in lab.calls)


@pytest.mark.parametrize("name,snapshot", [("wrong/name", "clean"), ("lab-120", "../clean"), ("lab-120", "current"), ("", "clean")])
def test_reset_rejects_invalid_guards_without_requests(monkeypatch, name, snapshot):
    lab = Lab(monkeypatch)
    with pytest.raises(ProxmoxError):
        lab.client.reset("120", name=name, snapshot=snapshot)
    assert lab.calls == []


def test_reset_stops_on_failed_task_without_rollback_or_secret_echo(monkeypatch):
    lab = Lab(monkeypatch, running=True)

    def failed(*_, **__):
        raise ProxmoxError("private-secret https://private-config")

    monkeypatch.setattr(lab.client, "wait_task", failed)
    with pytest.raises(ProxmoxError, match="reset stop failed") as exc:
        lab.reset()
    assert "private" not in str(exc.value)
    assert not any(path.endswith("/rollback") for _, path, _ in lab.calls)


@pytest.mark.parametrize("fault", ["parent", "running", "name", "task-result"])
def test_reset_never_claims_success_on_failed_post_verification(monkeypatch, fault):
    lab = Lab(monkeypatch)
    original = lab.request

    def request(method, path, **kwargs):
        result = original(method, path, **kwargs)
        if method == "POST" and path.endswith("/rollback"):
            if fault == "parent":
                lab.parent = "wrong"
            elif fault == "name":
                lab.status["name"] = lab.config["name"] = "wrong"
            elif fault == "running":
                lab.running = True
        if fault == "running" and method == "POST" and path.endswith("/stop"):
            lab.running = True
        if fault == "task-result" and "/tasks/" in path:
            return {"status": "stopped"}
        return result

    monkeypatch.setattr(lab.client, "request", request)
    with pytest.raises(ProxmoxError):
        lab.reset()


def test_observe_redacts_transport_errors(monkeypatch):
    lab = Lab(monkeypatch)
    lab.overrides["/nodes/node/qemu/120/config"] = ProxmoxError("private-secret https://private-config")
    with pytest.raises(ProxmoxError) as exc:
        lab.client.observe(["120"], "local-lvm")
    assert "private" not in str(exc.value)


def test_public_cli_json_and_remote_dispatch(monkeypatch):
    calls = []

    class Http:
        def _global_url(self, path):
            return path

        def post(self, url, json):
            calls.append((url, json))
            return {"result": {
                "vms": [{"vmid": int(vmid), "name": f"lab-{vmid}", "status": "stopped", "uptime": 0, "lock": None,
                         "snapshots": ["clean"], "latest_tasks": {"qmstart": None, "qmrollback": None}}
                        for vmid in json["args"]["vmids"]],
                "storage": {"name": "local-lvm", "total": 100, "used": 40, "available": 60},
            } if json["op"] == "observe" else {"vmid": 120, "name": "lab-120", "snapshot": "clean", "status": "stopped"}}

    monkeypatch.setattr(vm.ProxmoxClient, "for_lab", lambda: RemoteProxmoxClient.for_lab(Http()))
    runner = CliRunner()
    for command in (["observe", "120", "121", "--storage", "local-lvm"],
                    ["reset", "120", "--name", "lab-120", "--snapshot", "clean"]):
        result = runner.invoke(vm.app, command)
        assert result.exit_code == 0, result.output
        assert isinstance(json.loads(result.output), dict)
    assert calls == [("/vm/op", {"op": "observe", "vmid": None, "args": {"vmids": ["120", "121"], "storage": "local-lvm"}}),
                     ("/vm/op", {"op": "reset", "vmid": "120", "args": {"name": "lab-120", "snapshot": "clean"}})]


def test_cli_invalid_input_never_constructs_client_and_failure_has_no_partial_json(monkeypatch):
    def unexpected():
        raise AssertionError("client must not be constructed")

    monkeypatch.setattr(vm, "ProxmoxClient", unexpected)
    result = CliRunner().invoke(vm.app, ["observe", "120", "120", "--storage", "local-lvm"])
    assert result.exit_code == 1 and "unique" in result.output
    assert '"vms"' not in result.output


@pytest.mark.parametrize("error", [RuntimeError("private-secret https://config"), APIError(400, {"message": "private-secret"})])
def test_remote_redacts_transport_and_api_errors(error):
    class Http:
        def _global_url(self, path):
            return path

        def post(self, *_, **__):
            raise error

    with pytest.raises(ProxmoxError) as exc:
        RemoteProxmoxClient.for_lab(Http()).observe(["120"], "local-lvm")
    assert "private" not in str(exc.value)


@pytest.mark.parametrize("op,result", [("observe", None), ("reset", None), ("observe", {"vms": [], "storage": {}})])
def test_remote_refuses_missing_success_result(op, result):
    class Http:
        def _global_url(self, path):
            return path

        def post(self, *_, **__):
            return {"result": result}

    remote = RemoteProxmoxClient.for_lab(Http())
    with pytest.raises(ProxmoxError):
        remote.observe(["120"], "local-lvm") if op == "observe" else remote.reset("120", name="lab-120", snapshot="clean")


def test_cli_configuration_error_is_redacted(monkeypatch):
    def fail():
        raise ProxmoxError("private-secret https://private-config")

    monkeypatch.setattr(vm.ProxmoxClient, "for_lab", fail)
    result = CliRunner().invoke(vm.app, ["observe", "120", "--storage", "local-lvm"])
    assert result.exit_code == 1 and "private" not in result.output


@pytest.fixture()
def local_pve(monkeypatch, tmp_path):
    """Real CLI construction and PVE HTTP seam; all credentials are synthetic."""
    lab, authorizations = Lab(monkeypatch), []
    ca = tmp_path / "ca.pem"
    ca.write_text("fixture")
    for key, value in {
        "PROXMOX_API_URL": "https://fixture", "PROXMOX_NODE": "node", "PROXMOX_TOKEN_ID": "fixture@pve!scoped",
        "PROXMOX_TOKEN_SECRET": "scoped-fixture", "PROXMOX_CA_BUNDLE": str(ca),
        "PROXMOX_ADMIN_TOKEN": "fixture@pve!admin=admin-fixture",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(proxmox, "_read_env_file", lambda _: {})
    monkeypatch.setattr(proxmox, "_tls_context", lambda _: None)

    def request(method, url, headers, **kwargs):
        authorizations.append(headers["Authorization"])
        return httpx.Response(200, json={"data": lab.request(method, url.split("/api2/json", 1)[1], **kwargs)})

    monkeypatch.setattr(proxmox.httpx, "request", request)
    return lab, authorizations


LAB_COMMANDS = [["observe", "120", "--storage", "local-lvm"], ["reset", "120", "--name", "lab-120", "--snapshot", "clean"]]


@pytest.mark.parametrize("command", LAB_COMMANDS)
def test_direct_lab_cli_never_uses_admin_environment_token(local_pve, command):
    _, authorizations = local_pve
    result = CliRunner().invoke(vm.app, command)
    assert result.exit_code == 0, result.output
    assert authorizations and set(authorizations) == {"PVEAPIToken=fixture@pve!scoped=scoped-fixture"}


@pytest.mark.parametrize("command", LAB_COMMANDS)
def test_remote_lab_cli_never_sends_admin_environment_header(monkeypatch, command):
    lab, seen = Lab(monkeypatch), []
    monkeypatch.setattr(proxmox, "_read_env_file", lambda _: {})
    for key in ("PROXMOX_API_URL", "PROXMOX_NODE", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET", "PROXMOX_CA_BUNDLE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PROXMOX_ADMIN_TOKEN", "fixture@pve!admin=admin-fixture")

    class Http:
        _client = SimpleNamespace(headers={})

        def _global_url(self, path):
            return path

        def post(self, _, json):
            seen.append(dict(self._client.headers))
            return {"result": lab.client.observe(**json["args"]) if json["op"] == "observe" else lab.reset()}

    monkeypatch.setattr("cli.lib.proxmox_remote.STClient", lambda **_: Http())
    result = CliRunner().invoke(vm.app, command)
    assert result.exit_code == 0, result.output
    assert seen == [{}]


@pytest.mark.parametrize("error", [httpx.InvalidURL("private-secret https://private-config"), OSError("private-secret"),
    ssl.SSLError("private-secret"), json.JSONDecodeError("private-secret", "private-config", 0)])
@pytest.mark.parametrize("phase", ["request", "wait", "task-result"])
def test_lab_expected_failures_are_bounded_proxmox_errors(monkeypatch, error, phase):
    lab = Lab(monkeypatch, running=True)
    if phase == "request":
        lab.overrides["/nodes/node/qemu/120/config"] = error
    elif phase == "wait":
        def fail(*_, **__):
            raise error

        monkeypatch.setattr(lab.client, "wait_task", fail)
    else:
        original = lab.request

        def request(method, path, **kwargs):
            if "/tasks/" in path:
                raise error
            return original(method, path, **kwargs)

        monkeypatch.setattr(lab.client, "request", request)
    with pytest.raises(ProxmoxError) as exc:
        lab.reset()
    assert len(str(exc.value)) < 180 and "private" not in str(exc.value) and exc.value.__suppress_context__


@pytest.mark.parametrize("error", [OSError("private-secret https://private-config"), ssl.SSLError("private-secret"),
    json.JSONDecodeError("private-secret", "private-config", 0)])
def test_lab_configuration_loading_errors_are_redacted(monkeypatch, error):
    def fail(_):
        raise error

    monkeypatch.setattr(proxmox, "_read_env_file", fail)
    with pytest.raises(ProxmoxError) as exc:
        ProxmoxClient.for_lab()
    assert len(str(exc.value)) < 180 and "private" not in str(exc.value) and exc.value.__suppress_context__


@pytest.mark.parametrize("command", LAB_COMMANDS)
@pytest.mark.parametrize("seam", ["http", "tls"])
def test_direct_lab_cli_transport_and_tls_errors_have_no_traceback(local_pve, monkeypatch, command, seam):
    def fail(*_, **__):
        raise httpx.InvalidURL("private-secret https://private-config")

    monkeypatch.setattr(proxmox.httpx if seam == "http" else proxmox, "request" if seam == "http" else "_tls_context", fail)
    result = CliRunner().invoke(vm.app, command)
    assert result.exit_code == 1 and "private" not in result.output and "Traceback" not in result.output
    assert isinstance(result.exception, SystemExit)


def test_default_clients_cannot_reuse_owner_elevation_for_lab_operations(local_pve):
    for client in (ProxmoxClient(), RemoteProxmoxClient(SimpleNamespace(_client=SimpleNamespace(headers={})))):
        for operation in (lambda client=client: client.observe(["120"], "local-lvm"),
                          lambda client=client: client.reset("120", name="lab-120", snapshot="clean")):
            with pytest.raises(ProxmoxError, match="unelevated"):
                operation()
    assert local_pve[1] == []
