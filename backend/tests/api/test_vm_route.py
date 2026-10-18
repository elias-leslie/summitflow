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
