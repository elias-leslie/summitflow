"""Runtime browser authority and lease lifetime boundaries."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.access_control import AccessPrincipal
from app.api import browser_sessions as api


def session(**changes: Any) -> dict[str, Any]:
    return {"name": "agent-a", "actor": "agent:one", "state": "active", "paused": True,
            "runtime_state": "running", "last_used_ms": 10, **changes}


def view(**changes: Any) -> dict[str, Any]:
    return {"schema_version": 1, "status": "leased", **session(),
            "stream": {"enabled": True, "port": 45678},
            "binding": {"session": "agent-a", "target_id": "target-one", "document_id": "doc-one"},
            "page": {"url": "http://fixture.test", "title": "Fixture"}, **changes}


@contextmanager
def client(role: str = "owner", local: bool = False, module=api):
    app = FastAPI()

    @app.middleware("http")
    async def principal(request: Request, call_next):
        request.state.principal = AccessPrincipal("operator@example.test", role, True, local) if role != "none" else None
        return await call_next(request)

    app.include_router(module.router)
    with TestClient(app) as connection:
        yield connection


@pytest.mark.parametrize("role", ["viewer", "none"])
def test_inventory_and_controls_require_owner(monkeypatch, role: str) -> None:
    async def forbidden(*_args, **_kwargs):
        pytest.fail("unauthorized request must not reach browser owner")
    monkeypatch.setattr(api, "_owner_command", forbidden)
    with client(role) as connection:
        assert connection.get("/api/browser-sessions").status_code == 403
        assert connection.post("/api/browser-sessions/agent-a/pause", json={"actor": "agent:one"}).status_code == 403


def test_inventory_is_private_and_excludes_paths_and_stream_authority(monkeypatch) -> None:
    async def command(args, actor=None):
        assert args == ["list", "--all"] and actor is None
        return {"schema_version": 1, "sessions": [session(profile="private", stream={"port": 45678})]}
    monkeypatch.setattr(api, "_owner_command", command)
    with client() as connection:
        response = connection.get("/api/browser-sessions")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["sessions"] == [session()]


def test_control_rejects_cross_origin_stale_owner_and_unknown_commands(monkeypatch) -> None:
    calls = []
    async def command(args, actor=None):
        calls.append((args, actor))
        return {"schema_version": 1, "sessions": [session()]}
    monkeypatch.setattr(api, "_owner_command", command)
    with client() as connection:
        assert connection.post("/api/browser-sessions/agent-a/pause", json={"actor": "agent:one"}, headers={"Origin": "https://other.test"}).status_code == 403
        assert calls == []
        assert connection.post("/api/browser-sessions/agent-a/pause", json={"actor": "new-owner"}, headers={"Origin": "http://testserver"}).status_code == 409
        assert connection.post("/api/browser-sessions/agent-a/arbitrary", json={"actor": "agent:one"}, headers={"Origin": "http://testserver"}).status_code == 404
    assert calls == [(["list", "--all"], None)]


def test_control_uses_selected_owner_and_keeps_closed_state_visible(monkeypatch) -> None:
    calls = []
    current = session()
    async def command(args, actor=None):
        calls.append((args, actor))
        if args == ["close", "agent-a"]:
            current["state"] = "closed"
            current["paused"] = False
            return {"schema_version": 1}
        return {"schema_version": 1, "sessions": [current]}
    monkeypatch.setattr(api, "_owner_command", command)
    with client() as connection:
        response = connection.post("/api/browser-sessions/agent-a/close", json={"actor": "agent:one"}, headers={"Origin": "http://testserver"})
    assert response.status_code == 200
    assert response.json()["session"]["state"] == "closed"
    assert calls[1] == (["close", "agent-a"], "agent:one")


def test_forwarded_remote_call_cannot_inherit_local_bypass(monkeypatch) -> None:
    with client(local=True) as connection:
        assert connection.get("/api/browser-sessions", headers={"X-Forwarded-For": "127.0.0.1, 10.0.0.8"}).status_code == 403


@pytest.mark.asyncio
async def test_owner_transport_is_canonical_and_errors_do_not_echo_page_data(monkeypatch) -> None:
    async def run(args, **kwargs):
        assert args[1:] == ["--no-compact", "browser", "--local-ai", "session", "status", "agent-a"]
        assert kwargs["env"]["ST_BROWSER_OWNER"] == "agent:one"
        return subprocess.CompletedProcess(args, 75, "private page content", "private page content")
    monkeypatch.setattr(api, "run_async", run)
    with pytest.raises(api.HTTPException) as error:
        await api._owner_command(["status", "agent-a"], "agent:one")
    assert error.value.status_code == 409
    assert "private" not in str(error.value.detail)


@pytest.mark.parametrize("raw", [
    '{"type":"command","command":"eval"}',
    '{"type":"input_keyboard","eventType":"keyDown","url":"ws://remote"}',
    '{"type":"input_mouse","eventType":"mousePressed","x":true,"y":0}',
    '{"type":"input_mouse","eventType":"mousePressed","x":NaN,"y":0}',
    '{"type":"ack","seq":true}',
])
def test_native_input_rejects_commands_unknown_fields_and_invalid_numbers(raw: str) -> None:
    with pytest.raises(ValueError):
        api._input_event(raw)


def test_display_locations_exclude_credentials_queries_and_fragments() -> None:
    assert api._display_url("https://user:private@fixture.test/callback?code=private&token=private#private") == "https://fixture.test/callback"
    assert api._display_url("javascript:private") == ""


class Lease:
    def __init__(self):
        self.ended = False
    async def readline(self):
        return (json.dumps(view()) + "\n").encode()
    def poll(self):
        return 0 if self.ended else None
    def close_stdin(self):
        self.ended = True
    def close(self):
        pass


class Stream:
    def __init__(self, target="target-one"):
        self.target = target
        self.closed = False
        self.sent: list[dict[str, Any]] = []
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_args):
        await self.close()
    async def close(self):
        self.closed = True
    async def send(self, raw):
        self.sent.append(json.loads(raw))
    async def __aiter__(self):
        yield json.dumps({"type": "tabs", "tabs": [{"active": True, "tabId": "t1", "targetId": self.target}]})
        yield json.dumps({"type": "frame", "seq": 1, "data": "fixture", "metadata": {"deviceWidth": 10, "deviceHeight": 10}})
        await asyncio.Event().wait()


def stream_fixture(monkeypatch, target="target-one"):
    lease, stream = Lease(), Stream(target)
    async def command(args, actor=None):
        if args[0] == "resume":
            assert lease.ended, "resume must wait for owner lease EOF/reap"
        return {"schema_version": 1, "sessions": [session()]}
    monkeypatch.setattr(api, "_owner_command", command)
    monkeypatch.setattr(api, "resolve_principal", lambda _request: AccessPrincipal("operator@example.test", "owner", True))
    def spawn(args, env):
        assert args[-3:] == ["session", "lease", "agent-a"]
        assert env["ST_BROWSER_OWNER"] == "agent:one"
        return lease
    def connect(url, **kwargs):
        assert url == "ws://127.0.0.1:45678/?pacing=ack&maxFps=15"
        assert kwargs["proxy"] is None
        return stream
    monkeypatch.setattr(api, "spawn_duplex", spawn)
    monkeypatch.setattr(api, "connect", connect)
    return lease, stream


def another_worker():
    spec = importlib.util.spec_from_file_location("app.api.browser_sessions_worker_b", api.__file__)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._connections is not api._connections
    return module


def test_stream_relays_only_bound_target_and_releases_before_resume(monkeypatch) -> None:
    lease, stream = stream_fixture(monkeypatch)
    with client() as connection, connection.websocket_connect("/ws/browser-sessions/agent-a?actor=agent:one", headers={"Origin": "http://testserver"}) as ws:
        assert ws.receive_json()["type"] == "bound"
        assert ws.receive_json()["type"] == "frame"
        ws.send_json({"type": "ack", "seq": 1})
        response = connection.post("/api/browser-sessions/agent-a/resume", json={"actor": "agent:one"}, headers={"Origin": "http://testserver"})
        assert response.status_code == 200
    assert lease.ended
    assert stream.sent[0] == {"type": "config", "pacing": "ack", "maxFps": 15}


@pytest.mark.parametrize("action", ["resume", "close"])
def test_owning_client_releases_before_lifecycle_http_on_another_worker(monkeypatch, action) -> None:
    lease, stream = stream_fixture(monkeypatch)
    original_close = lease.close_stdin
    def close_stdin():
        assert stream.closed, "upstream input channel must close before owner unlock"
        original_close()
    monkeypatch.setattr(lease, "close_stdin", close_stdin)
    worker_b = another_worker()

    async def command(args, actor=None):
        if args == [action, "agent-a"] and not lease.ended:
            raise api.HTTPException(409, "Browser session is busy")
        return {"schema_version": 1, "sessions": [session()]}
    monkeypatch.setattr(worker_b, "_owner_command", command)

    with client() as worker_a_client, client(module=worker_b) as worker_b_client, worker_a_client.websocket_connect("/ws/browser-sessions/agent-a?actor=agent:one", headers={"Origin": "http://testserver"}) as ws:
        assert ws.receive_json()["type"] == "bound"
        assert ws.receive_json()["type"] == "frame"
        headers, body = {"Origin": "http://testserver"}, {"actor": "agent:one"}
        assert worker_b_client.post(f"/api/browser-sessions/agent-a/{action}", headers=headers, json=body).status_code == 409
        ws.send_json({"type": "release"})
        assert ws.receive_json() == {"type": "released"}
        assert lease.ended, "release acknowledgement must follow owner EOF/reap"
        assert worker_b_client.post(f"/api/browser-sessions/agent-a/{action}", headers=headers, json=body).status_code == 200
    assert not any(item["type"] == "release" for item in stream.sent)


def test_target_change_ends_view_instead_of_switching(monkeypatch) -> None:
    lease, _stream = stream_fixture(monkeypatch, target="another-target")
    with client() as connection, connection.websocket_connect("/ws/browser-sessions/agent-a?actor=agent:one", headers={"Origin": "http://testserver"}) as ws:
        assert ws.receive_json()["type"] == "bound"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert lease.ended


@pytest.mark.parametrize("origin", [None, "https://other.test"])
def test_stream_authenticates_and_checks_actual_origin(monkeypatch, origin) -> None:
    stream_fixture(monkeypatch)
    headers = {"Sec-Fetch-Site": "same-origin"}
    if origin:
        headers["Origin"] = origin
    with client() as connection, pytest.raises(WebSocketDisconnect), connection.websocket_connect("/ws/browser-sessions/agent-a?actor=agent:one", headers=headers):
        pass


def test_stream_rejects_viewer_before_owner_dispatch(monkeypatch) -> None:
    stream_fixture(monkeypatch)
    monkeypatch.setattr(api, "resolve_principal", lambda _request: AccessPrincipal("viewer@example.test", "viewer", True))
    with client() as connection, pytest.raises(WebSocketDisconnect), connection.websocket_connect("/ws/browser-sessions/agent-a?actor=agent:one", headers={"Origin": "http://testserver"}):
        pass


def test_unpaused_session_cannot_acquire_human_lease(monkeypatch) -> None:
    lease, _stream = stream_fixture(monkeypatch)
    async def command(_args, actor=None):
        return {"schema_version": 1, "sessions": [session(paused=False)]}
    monkeypatch.setattr(api, "_owner_command", command)
    with client() as connection, pytest.raises(WebSocketDisconnect), connection.websocket_connect("/ws/browser-sessions/agent-a?actor=agent:one", headers={"Origin": "http://testserver"}):
        pass
    assert not lease.ended  # no lease was started at all


def test_stream_revocation_stops_live_inputs_and_releases_lease(monkeypatch) -> None:
    lease, stream = stream_fixture(monkeypatch)
    with client() as connection, connection.websocket_connect("/ws/browser-sessions/agent-a?actor=agent:one", headers={"Origin": "http://testserver"}) as ws:
        assert ws.receive_json()["type"] == "bound"
        assert ws.receive_json()["type"] == "frame"
        monkeypatch.setattr(api, "resolve_principal", lambda _request: None)
        ws.send_json({"type": "input_keyboard", "eventType": "keyDown", "key": "x", "code": "KeyX"})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert lease.ended
    assert not any(item["type"] == "input_keyboard" for item in stream.sent)


@pytest.mark.skipif(os.environ.get("ST_BROWSER_LIVE_FIXTURE") != "1", reason="explicit isolated fixture gate")
@pytest.mark.asyncio
async def test_live_owner_lease_proxy_preserves_same_target_and_blocks_resume(monkeypatch, tmp_path) -> None:
    """Opt-in real public ST integration; only a root-approved synthetic fixture."""
    name, actor = "runtime-proxy-fixture", "runtime:proxy-fixture"
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("ST_BROWSER_OWNER", actor)
    monkeypatch.setattr(api, "resolve_principal", lambda _request: AccessPrincipal("operator@example.test", "owner", True))
    await api._owner_command(["create", name], actor)

    async def core(*args: str):
        result = await api.run_async([
            str(api._st_cli_path()), "--no-compact", "browser", "--local-ai", "--session", name, *args,
        ], env=dict(os.environ), capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, "public owner fixture command failed"
        return result.stdout

    try:
        await core("open", "http://127.0.0.1:46597/task/intake?run=runtime-human-1")
        position = json.loads(await core("step", "eval", "(() => {const r=document.querySelector('input[name=name]').getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()"))["completed"][0]["result"]["result"]
        await api._owner_command(["pause", name], actor)
        with client() as connection, connection.websocket_connect(f"/ws/browser-sessions/{name}?actor={actor}", headers={"Origin": "http://testserver"}) as ws:
            bound = ws.receive_json()
            assert bound["type"] == "bound" and bound["binding"]["session"] == name
            assert bound["page"]["url"] == "http://127.0.0.1:46597/task/intake"
            frame = ws.receive_json()
            assert frame["type"] == "frame" and frame["seq"] >= 0
            ws.send_json({"type": "ack", "seq": frame["seq"]})
            with pytest.raises(api.HTTPException) as error:
                await api._owner_command(["resume", name], actor)
            assert error.value.status_code == 409
            for event_type in ("mousePressed", "mouseReleased"):
                ws.send_json({"type": "input_mouse", "eventType": event_type, "x": position["x"], "y": position["y"], "button": "left", "clickCount": 1, "modifiers": 0})
                while ws.receive_json()["type"] != "input_forwarded":
                    pass
            ws.send_json({"type": "input_keyboard", "eventType": "keyDown", "key": "r", "code": "KeyR", "text": "r", "windowsVirtualKeyCode": 82, "modifiers": 0})
            while True:
                event = ws.receive_json()
                if event["type"] == "frame":
                    ws.send_json({"type": "ack", "seq": event["seq"]})
                if event["type"] == "input_forwarded":
                    break
            ws.send_json({"type": "input_keyboard", "eventType": "keyUp", "key": "r", "code": "KeyR", "windowsVirtualKeyCode": 82, "modifiers": 0})
            while ws.receive_json()["type"] != "input_forwarded":
                pass
            ws.send_json({"type": "input_keyboard", "eventType": "char", "text": "u"})
            while ws.receive_json()["type"] != "input_forwarded":
                pass
            ws.send_json({"type": "release"})
            while ws.receive_json()["type"] != "released":
                pass
            with client(module=another_worker()) as other_worker:
                response = other_worker.post(f"/api/browser-sessions/{name}/resume", json={"actor": actor}, headers={"Origin": "http://testserver"})
                assert response.status_code == 200
        value = json.loads(await core("step", "get", "value", "input[name=name]"))
        assert value["status"] == "complete"
        assert value["completed"][0]["result"]["value"] == "ru"
    finally:
        await api._owner_command(["close", name], actor)
