"""POST /api/vm/op: a pass-through to ProxmoxClient for callers without a Proxmox token."""

from __future__ import annotations

from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from app import access_control
from app.api import vm as vm_api
from app.main import app
from cli.lib.proxmox import ProxmoxError

AGENT = access_control.AccessPrincipal(email="agent@summitflow.local", role="agent", is_active=True)


class FakeClient:
    calls: ClassVar[list] = []

    @classmethod
    def for_lab(cls):
        return cls()

    def status(self, vmid, **kwargs):
        self.calls.append(("status", vmid, kwargs))
        return {"vmid": vmid, "status": "running"}

    def start(self, vmid, **kwargs):
        self.calls.append(("start", vmid, kwargs))
        raise ProxmoxError('Proxmox API error 403: {"message":"Permission check failed (/vms/140, VM.PowerMgmt)"}')

    def observe(self, **kwargs):
        self.calls.append(("observe", None, kwargs))
        return {"vms": [], "storage": {}}

    def reset(self, vmid, **kwargs):
        self.calls.append(("reset", vmid, kwargs))
        return {"vmid": int(vmid), "status": "stopped"}


@pytest.fixture()
def api(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr(vm_api, "ProxmoxClient", FakeClient)
    monkeypatch.setattr(access_control, "resolve_principal", lambda request: AGENT)
    return TestClient(app)


def test_route_forwards_an_op_for_an_agent(api):
    response = api.post("/api/vm/op", json={"op": "status", "vmid": "191"})
    assert response.status_code == 200
    assert response.json() == {"result": {"vmid": "191", "status": "running"}}
    assert FakeClient.calls == [("status", "191", {})]


def test_route_returns_the_proxmox_error_unchanged_and_skips_lab_declaration(api):
    response = api.post("/api/vm/op", json={"op": "start", "vmid": "140"})
    assert response.status_code == 400
    assert "Permission check failed (/vms/140, VM.PowerMgmt)" in response.json()["message"]
    assert FakeClient.calls == [("start", "140", {"declare_lab": False})]


def test_route_refuses_methods_outside_the_list(api):
    for body in ({"op": "request", "vmid": "191"}, {"op": "status", "vmid": "191", "args": {"x": 1}}):
        assert api.post("/api/vm/op", json=body).status_code == 400
    assert FakeClient.calls == []


def test_route_forwards_only_explicit_lab_operation_arguments(api):
    observe = {"op": "observe", "args": {"vmids": ["120"], "storage": "local-lvm"}}
    reset = {"op": "reset", "vmid": "120", "args": {"name": "lab-120", "snapshot": "clean"}}
    assert api.post("/api/vm/op", json=observe).json() == {"result": {"vms": [], "storage": {}}}
    assert api.post("/api/vm/op", json=reset).json() == {"result": {"vmid": 120, "status": "stopped"}}
    assert FakeClient.calls == [("observe", None, observe["args"]), ("reset", "120", reset["args"])]


@pytest.mark.parametrize("body", [
    {"op": "observe", "args": {"vmids": ["120"]}},
    {"op": "observe", "vmid": "120", "args": {"vmids": ["120"], "storage": "local-lvm"}},
    {"op": "observe", "args": {"vmids": ["120", "120"], "storage": "local-lvm"}},
    {"op": "observe", "args": {"vmids": "120", "storage": "local-lvm"}},
    {"op": "observe", "args": {"vmids": ["120"], "storage": "../other"}},
    {"op": "reset", "args": {"name": "lab-120", "snapshot": "clean"}},
    {"op": "reset", "vmid": "120", "args": {"name": "lab-120", "snapshot": "clean", "start": True}},
    {"op": "reset", "vmid": "120/stop", "args": {"name": "lab-120", "snapshot": "clean"}},
    {"op": "reset", "vmid": "120", "args": {"name": "lab-120", "snapshot": "current"}},
])
def test_route_rejects_malformed_lab_operations_before_client_calls(api, body):
    assert api.post("/api/vm/op", json=body).status_code == 400
    assert FakeClient.calls == []


def test_lab_route_does_not_echo_failed_client_configuration(api, monkeypatch):
    def fail():
        raise ProxmoxError("private-secret https://private-config")

    monkeypatch.setattr(vm_api.ProxmoxClient, "for_lab", fail)
    response = api.post("/api/vm/op", json={"op": "observe", "args": {"vmids": ["120"], "storage": "local-lvm"}})
    assert response.status_code == 400
    assert "private" not in response.text


def test_unauthenticated_call_is_refused(monkeypatch):
    monkeypatch.setattr(vm_api, "ProxmoxClient", FakeClient)
    monkeypatch.setattr(access_control, "resolve_principal", lambda request: None)
    FakeClient.calls = []
    assert TestClient(app).post("/api/vm/op", json={"op": "status", "vmid": "191"}).status_code == 401
    assert FakeClient.calls == []


ADMIN = "summitflow@pve!prod-admin=s3cret-value"


@pytest.fixture()
def real_client(monkeypatch):
    """Real ProxmoxClient, stubbed Proxmox HTTP: records the Authorization header of each call."""
    from cli.lib import proxmox

    seen = []
    config = proxmox.ProxmoxConfig("https://pve", "summitflow@pve!backend", "backend-secret", "node")
    monkeypatch.setattr(proxmox, "load_proxmox_config", lambda: config)
    monkeypatch.setattr(proxmox, "_tls_context", lambda _: None)

    def fake_request(method, url, headers, **_):
        seen.append(headers["Authorization"])
        return proxmox.httpx.Response(200, json={"data": [{"vmid": 1, "type": "qemu"}]})

    monkeypatch.setattr(proxmox.httpx, "request", fake_request)
    monkeypatch.setattr(access_control, "resolve_principal", lambda request: AGENT)
    return seen


def test_admin_header_swaps_the_token_for_that_request_only(real_client):
    api = TestClient(app)
    body = {"op": "list_vms"}
    assert api.post("/api/vm/op", json=body, headers={"X-Proxmox-Admin-Token": ADMIN}).status_code == 200
    assert api.post("/api/vm/op", json=body).status_code == 200
    assert real_client == [
        "PVEAPIToken=summitflow@pve!prod-admin=s3cret-value",
        "PVEAPIToken=summitflow@pve!backend=backend-secret",
    ]


def test_malformed_admin_header_is_refused_without_echo(real_client):
    response = TestClient(app).post("/api/vm/op", json={"op": "list_vms"}, headers={"X-Proxmox-Admin-Token": "nosplit-secret"})
    assert response.status_code == 400
    assert "nosplit-secret" not in response.text
    assert real_client == []


@pytest.mark.parametrize("op", ["observe", "reset"])
def test_lab_api_rejects_admin_header_before_constructing_client(api, monkeypatch, op):
    constructed = []
    monkeypatch.setattr(vm_api, "ProxmoxClient", lambda: constructed.append(True) or FakeClient())
    body = {"op": op, "args": {"vmids": ["120"], "storage": "local-lvm"}} if op == "observe" else {
        "op": op, "vmid": "120", "args": {"name": "lab-120", "snapshot": "clean"},
    }
    response = api.post("/api/vm/op", json=body, headers={"X-Proxmox-Admin-Token": ADMIN})
    assert response.status_code == 400
    assert constructed == [] and FakeClient.calls == []
    assert ADMIN not in response.text


@pytest.mark.parametrize("op", ["observe", "reset"])
def test_lab_api_never_uses_admin_environment_token(monkeypatch, tmp_path, op):
    from cli.lib import proxmox

    ca, seen = tmp_path / "ca.pem", []
    ca.write_text("fixture")
    monkeypatch.setattr(proxmox, "_read_env_file", lambda _: {})
    monkeypatch.setattr(proxmox, "_tls_context", lambda _: None)
    for key, value in {
        "PROXMOX_API_URL": "https://fixture", "PROXMOX_NODE": "node", "PROXMOX_TOKEN_ID": "fixture@pve!scoped",
        "PROXMOX_TOKEN_SECRET": "scoped-fixture", "PROXMOX_CA_BUNDLE": str(ca), "PROXMOX_ADMIN_TOKEN": ADMIN,
    }.items():
        monkeypatch.setenv(key, value)

    def request(*_, headers, **__):
        seen.append(headers["Authorization"])
        return proxmox.httpx.Response(200, json={"data": {}})

    def lab_op(client, *_, **__):
        return client.request("GET", "/nodes/node/qemu/120/status/current")

    monkeypatch.setattr(proxmox.httpx, "request", request)
    monkeypatch.setattr(proxmox.ProxmoxClient, op, lab_op)
    monkeypatch.setattr(access_control, "resolve_principal", lambda request: AGENT)
    body = {"op": op, "args": {"vmids": ["120"], "storage": "local-lvm"}} if op == "observe" else {
        "op": op, "vmid": "120", "args": {"name": "lab-120", "snapshot": "clean"},
    }
    assert TestClient(app).post("/api/vm/op", json=body).status_code == 200
    assert seen == ["PVEAPIToken=fixture@pve!scoped=scoped-fixture"]


def test_header_elevated_client_cannot_be_reused_for_lab_operations(real_client):
    client = vm_api.request_client(ADMIN)
    for operation in (lambda: client.observe(["120"], "local-lvm"), lambda: client.reset("120", name="lab-120", snapshot="clean")):
        with pytest.raises(ProxmoxError, match="unelevated"):
            operation()
    assert real_client == []


@pytest.mark.parametrize("error", [AttributeError("programming defect"), TypeError("programming defect"), ValueError("programming defect")])
def test_lab_api_programming_errors_surface(api, monkeypatch, error):
    def fail(**_):
        raise error

    monkeypatch.setattr(vm_api.ProxmoxClient, "for_lab", lambda: type("Broken", (), {"observe": staticmethod(fail)})())
    with pytest.raises(type(error)) as exc:
        api.post("/api/vm/op", json={"op": "observe", "args": {"vmids": ["120"], "storage": "local-lvm"}})
    assert exc.value is error
