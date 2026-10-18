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


    def status(self, vmid, **kwargs):
        self.calls.append(("status", vmid, kwargs))
        return {"vmid": vmid, "status": "running"}

    def start(self, vmid, **kwargs):
        self.calls.append(("start", vmid, kwargs))
        raise ProxmoxError('Proxmox API error 403: {"message":"Permission check failed (/vms/140, VM.PowerMgmt)"}')


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
