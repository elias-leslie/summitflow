"""Fleet endpoints retain owner authentication, privacy, and explicit gap errors."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.access_control import AccessPrincipal
from app.api import fleet_sessions as api
from app.storage.fleet_events import SourceKeyConflict, StaleCursor


@contextmanager
def _client(role="owner", *, local=False):
    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.principal = AccessPrincipal("fixture@example.test", role, True, local)
        return await call_next(request)

    app.include_router(api.router, prefix="/api")
    with TestClient(app) as client:
        yield client


def test_fleet_reads_and_writes_require_owner(monkeypatch):
    state = MagicMock(return_value={"root": "root-fixture", "project_id": "fixture"})
    monkeypatch.setattr(api.service, "root_state", state)
    with _client("viewer") as client:
        assert client.get("/api/fleet/v1/roots/root-fixture").status_code == 403
        assert client.post("/api/fleet/v1/roots/root-fixture/close").status_code == 403
    state.assert_not_called()
    with _client(local=True) as client:
        assert client.get("/api/fleet/v1/roots/root-fixture", headers={"X-Forwarded-For": "10.0.0.1"}).status_code == 403


def test_append_is_versioned_private_and_digest_scoped(monkeypatch):
    monkeypatch.setattr(api.service, "root_state", lambda root: {"project_id": "fixture"})
    append = MagicMock(return_value={"sequence": 7})
    monkeypatch.setattr(api, "append_fleet_event", append)
    body = {"source_key": "neri:run:1:revision:2", "event_type": "source.changed", "attributes": {"source_ref": "run:1"}, "digest": "a" * 64}
    with _client() as client:
        response = client.post("/api/fleet/v1/roots/root-fixture/events", json=body)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert client.post("/api/fleet/v1/roots/root-fixture/events", json=body, headers={"Origin": "https://other.example"}).status_code == 403
        assert client.post("/api/fleet/v1/roots/root-fixture/events", json={**body, "event_type": "root.closed"}).status_code == 422
        append.side_effect = SourceKeyConflict("revision differs")
        assert client.post("/api/fleet/v1/roots/root-fixture/events", json=body).status_code == 409
    assert append.call_args.args == ("fixture", "root-fixture")
    assert append.call_args.kwargs["require_open"] is True


def test_wait_exposes_stale_gap_and_defaults_to_300(monkeypatch):
    calls = []

    async def wait(root, *, cursor, timeout):
        calls.append((root, cursor, timeout))
        raise StaleCursor(cursor, 20)

    monkeypatch.setattr(api.service, "wait_events", wait)
    with _client() as client:
        response = client.get("/api/fleet/v1/roots/root-fixture/wait?cursor=3")
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "stale_cursor", "cursor": 3, "next_sequence": 20}
    assert calls == [("root-fixture", 3, 300)]


def test_start_uses_registered_project_root_not_client_path(monkeypatch):
    start = MagicMock(return_value={"root": "root-fixture", "capabilities": {"launch": "unavailable"}})
    monkeypatch.setattr(api.service, "start_root", start)
    monkeypatch.setattr(api, "get_project_root_path", lambda project: "/registered/fixture")
    with _client() as client:
        response = client.post("/api/fleet/v1/roots", json={"project_id": "fixture", "instruction": "Short source capsule"})
        assert response.status_code == 200
        assert start.call_args.kwargs["project_root"] == "/registered/fixture"
        invalid = client.post("/api/fleet/v1/roots", json={"project_id": "fixture", "project_root": "/injected", "instruction": "Short"})
        assert invalid.status_code == 422
