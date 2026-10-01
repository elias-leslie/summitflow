"""Owner boundary checks for the real managed-process HTTP adapter."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.access_control import AccessPrincipal
from app.api import agent_sessions


def client(monkeypatch, *, role="owner", local=False):
    app = FastAPI()

    @app.middleware("http")
    async def principal(request, call_next):
        if role:
            request.state.principal = AccessPrincipal(email="fixture@example.test", role=role, is_active=True, is_local_bypass=local)
        return await call_next(request)

    app.include_router(agent_sessions.router, prefix="/api/projects")
    calls = []

    def action(value, *, project_id):
        calls.append((value, project_id))
        if project_id != "summitflow":
            raise ValueError("binding mismatch")
        return {"capture_disabled": value == "disable", "project_id": project_id}

    monkeypatch.setattr(agent_sessions, "_managed_owner", lambda: SimpleNamespace(operator_status=lambda **_kwargs: {"available": True, "project_id": "summitflow"}, operator_action=action))
    return TestClient(app), calls


@pytest.mark.parametrize("role", [None, "viewer"])
def test_managed_routes_reject_nonowners(monkeypatch, role):
    http, calls = client(monkeypatch, role=role)
    assert http.get("/api/projects/managed-codex").status_code == 403
    assert http.post("/api/projects/summitflow/managed-codex/disable", headers={"origin": "http://testserver"}).status_code == 403
    assert not calls


def test_local_bypass_cannot_be_forwarded_by_remote_caller(monkeypatch):
    http, _ = client(monkeypatch, local=True)
    assert http.get("/api/projects/managed-codex", headers={"x-forwarded-for": "198.51.100.2, 127.0.0.1"}).status_code == 403


def test_managed_mutation_requires_same_origin_and_actual_project(monkeypatch):
    http, calls = client(monkeypatch)
    assert http.post("/api/projects/summitflow/managed-codex/disable", headers={"origin": "https://unrelated.example"}).status_code == 403
    assert not calls
    assert http.post("/api/projects/other/managed-codex/disable", headers={"origin": "http://testserver"}).status_code == 409
    response = http.post("/api/projects/summitflow/managed-codex/disable", headers={"origin": "http://testserver"})
    assert response.status_code == 200 and response.json()["capture_disabled"]
    assert response.headers["cache-control"] == "no-store"
    assert http.get("/api/projects/managed-codex").headers["cache-control"] == "no-store"
    assert calls == [("disable", "other"), ("disable", "summitflow")]


def test_managed_api_rejects_unknown_actions_and_never_accepts_paths(monkeypatch):
    http, calls = client(monkeypatch)
    assert http.post("/api/projects/summitflow/managed-codex/delete", headers={"origin": "http://testserver"}).status_code == 422
    assert not calls


def test_project_query_is_forwarded_to_same_owner_contract(monkeypatch):
    http, _ = client(monkeypatch)
    monkeypatch.setattr(agent_sessions, "_managed_owner", lambda: SimpleNamespace(operator_status=lambda *, project_id: {"project_id": project_id, "configured_projects": ["agent-hub", "summitflow"]}))
    assert http.get("/api/projects/managed-codex?project_id=agent-hub").json()["project_id"] == "agent-hub"


@pytest.fixture(autouse=True)
def isolated_managed_host_settings(tmp_path, monkeypatch):
    """Host policy must never make unit tests initialize the owner's real spools."""
    home = tmp_path / "isolated-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    for key in ("SUMMITFLOW_CODEX_MANAGED_CAPTURE", "SUMMITFLOW_CODEX_OUTBOX", "SUMMITFLOW_CODEX_OUTBOXES_JSON", "SUMMITFLOW_CODEX_OUTBOX_MAX_BYTES", "SUMMITFLOW_CODEX_RAW_RETENTION_SECONDS", "SUMMITFLOW_CODEX_PROTOCOL_QUALIFICATION"):
        monkeypatch.delenv(key, raising=False)


def test_update_failure_reports_safe_specific_stage_without_private_payload(monkeypatch):
    error_type = agent_sessions._managed_owner().ManagedUpdateError
    http, _ = client(monkeypatch)
    def failed(_action, *, project_id):
        raise error_type("delivery_credentials_unavailable", "qualify-update")
    monkeypatch.setattr(agent_sessions, "_managed_owner", lambda: SimpleNamespace(operator_action=failed, ManagedUpdateError=error_type))
    response = http.post("/api/projects/summitflow/managed-codex/qualify-update", headers={"origin": "http://testserver"})
    assert response.status_code == 409
    assert response.json()["detail"] == "Managed Codex update failed: delivery_credentials_unavailable (qualify-update)"
