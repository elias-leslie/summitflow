"""Fleet endpoints retain owner authentication, privacy, and explicit gap errors."""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from st_sdk.fleet import FleetClient
from st_sdk.http import APIError, BaseHTTPClient

from app.access_control import AccessPrincipal
from app.api import fleet_sessions as api
from app.storage import fleet_events
from app.storage.connection import get_connection
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


@pytest.fixture
def execution_fleet(ensure_test_project, tmp_path, monkeypatch):
    canonical = tmp_path / "registered" / ensure_test_project
    canonical.mkdir(parents=True)
    workspace = tmp_path / "workspaces"
    execution = workspace / "worktrees" / ensure_test_project / "fixture"
    execution.mkdir(parents=True)
    identity = json.dumps({"project": {"id": ensure_test_project}})
    for directory in (canonical, execution):
        (directory / "project.identity.json").write_text(identity)
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(workspace))
    monkeypatch.setattr(api, "get_project_root_path", lambda project: str(canonical))
    monkeypatch.setattr(fleet_events, "get_redis", lambda: MagicMock())
    launches = []

    def owner(surface, path, body, **kwargs):
        if kwargs.get("method") == "GET":
            raise httpx.ConnectError("Fixture owner has no read endpoint")
        launches.append(body)
        return {"owner": surface, "hostIdentity": "aabbccdd", "generation": "a" * 64,
                "logicalSessionId": "fixture-root", "surfaceLocator": "aico://widget/aabbccdd", "status": "running"}

    monkeypatch.setattr(api.service, "_host_request", owner)
    root = "root-" + uuid.uuid4().hex
    capsule = {"project_id": ensure_test_project, "instruction": "Review source.", "root": root}
    try:
        with _client() as api_client:
            def dispatch(request):
                return api_client.request(request.method, str(request.url), content=request.content,
                                          headers={"Content-Type": "application/json"})

            with BaseHTTPClient("http://fixture/api", ensure_test_project,
                                transport=httpx.MockTransport(dispatch)) as transport:
                yield FleetClient(transport), capsule, canonical, execution, launches
    finally:
        with get_connection() as conn:
            conn.execute("DELETE FROM events WHERE trace_id = %s", (root,))
            conn.commit()


@pytest.mark.parametrize("surface", ["aico", "a-term"])
@pytest.mark.parametrize("location", ["worktrees", "projects", "canonical", "nested"])
def test_sdk_start_retains_canonical_root_and_launches_in_execution_directory(execution_fleet, surface, location):
    sdk, capsule, canonical, execution, launches = execution_fleet
    if location == "canonical":
        execution = canonical
    elif location != "worktrees":
        destination = (canonical / "execution" if location == "nested"
                       else execution.parents[2] / "projects" / "fixture")
        destination.parent.mkdir(parents=True, exist_ok=True)
        execution.rename(destination)
        execution = destination
    state = sdk.start(**capsule, surface=surface, execution_root=str(execution))
    assert state["project_root"] == str(canonical)
    assert state["execution_root"] == str(execution)
    assert state["capabilities"]["launch"] == "host-acknowledged"
    assert launches[0]["projectRoot"] == str(execution)
    retained = sdk.show(state["root"])
    assert retained["project_root"] == str(canonical)
    assert retained["execution_root"] == str(execution)


def test_sdk_execution_directory_is_immutable_on_root_retry(execution_fleet):
    sdk, capsule, canonical, execution, launches = execution_fleet
    first = sdk.start(**capsule, execution_root=str(execution))
    assert sdk.start(**capsule, execution_root=str(execution))["root"] == first["root"]
    with pytest.raises(APIError) as changed:
        sdk.start(**capsule, execution_root=str(canonical))
    assert changed.value.status_code == 409
    with pytest.raises(APIError) as omitted:
        sdk.start(**capsule)
    assert omitted.value.status_code == 409
    assert len(launches) == 1
    assert sdk.show(first["root"])["execution_root"] == str(execution)


def test_sdk_default_execution_still_uses_registered_project_root(execution_fleet):
    sdk, capsule, canonical, _, launches = execution_fleet
    first = sdk.start(**capsule)
    assert first["project_root"] == first["execution_root"] == str(canonical)
    assert launches[0]["projectRoot"] == str(canonical)
    assert sdk.start(**capsule, execution_root=str(canonical))["root"] == first["root"]
    assert len(launches) == 1


@pytest.mark.parametrize("kind", ["relative", "missing", "file", "unnormalized", "symlink", "outside", "workspace-root", "foreign", "no-identity", "malformed-identity", "invalid-identity-shape"])
def test_sdk_start_rejects_invalid_execution_before_registering_or_launching(execution_fleet, kind):
    sdk, capsule, canonical, execution, launches = execution_fleet
    path = str(execution)
    if kind == "relative":
        path = "relative/fixture"
    elif kind == "missing":
        path = str(execution / "missing")
    elif kind == "file":
        path = str(execution / "project.identity.json")
    elif kind == "unnormalized":
        path = str(execution) + "/../fixture"
    elif kind == "symlink":
        link = execution.parent / "link"
        link.symlink_to(execution, target_is_directory=True)
        path = str(link)
    elif kind == "outside":
        outside = canonical.parent.parent / "scratch"
        outside.mkdir()
        (outside / "project.identity.json").write_text(json.dumps({"project": {"id": capsule["project_id"]}}))
        path = str(outside)
    elif kind == "workspace-root":
        path = str(execution.parents[2])
    elif kind == "foreign":
        (execution / "project.identity.json").write_text('{"project":{"id":"another-project"}}')
    elif kind == "no-identity":
        (execution / "project.identity.json").unlink()
    elif kind == "malformed-identity":
        (execution / "project.identity.json").write_text("not-json")
    elif kind == "invalid-identity-shape":
        (execution / "project.identity.json").write_text("[]")
    with pytest.raises(APIError) as error:
        sdk.start(**capsule, execution_root=path)
    assert error.value.status_code == 422
    assert launches == []
    with pytest.raises(APIError) as missing:
        sdk.show(capsule["root"])
    assert missing.value.status_code == 404


def test_sdk_legacy_root_retry_preserves_immutable_capsule(execution_fleet):
    sdk, capsule, canonical, _, launches = execution_fleet
    # Seed a retained pre-feature lifecycle row, as encountered after upgrade.
    fleet_events.append_fleet_event(capsule["project_id"], capsule["root"], source_key="root:start",
                                   event_type="root.started", attributes={
        "tool": "codex", "surface": "aico", "project_root": str(canonical),
        "instruction_digest": hashlib.sha256(b"Review source.").hexdigest(),
        "scope": {}, "role": "portfolio-root", "lead_root": None, "facet": None,
        "support_only": False, "offline": False,
    })
    fleet_events.append_fleet_event(capsule["project_id"], capsule["root"], source_key="root:host",
                                   event_type="root.host-unavailable", attributes={"capability": "unavailable"})
    state = sdk.start(**capsule)
    assert state["project_root"] == str(canonical)
    assert state["execution_root"] == str(canonical)
    assert state["capabilities"]["launch"] == "unavailable"
    assert sdk.show(capsule["root"])["execution_root"] == str(canonical)
    assert launches == []
