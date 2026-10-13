"""Runtime browser authority and lease lifetime boundaries."""

from __future__ import annotations

import asyncio
import json
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


@pytest.fixture(autouse=True)
def no_real_assist(monkeypatch):
    # Lifecycle changes stop an assist server; tests never reach systemd.
    monkeypatch.setattr(api, "_assist", lambda: FakeAssist())


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
    assert response.json()["sessions"] == [{**session(), "location": None, "pause_reason": None}]


@pytest.mark.parametrize(("runtime", "location"), [
    ({"target": "proxmox", "host": "10.0.0.5", "port": 9300}, "proxmox"),
    ({"target": "local-ai"}, "local"),
    (None, None),
    ({"target": "elsewhere"}, None),
    ("proxmox", None),
])
def test_inventory_reports_browser_location_without_endpoint(monkeypatch, runtime, location) -> None:
    async def command(args, actor=None):
        return {"schema_version": 1, "sessions": [session(runtime=runtime)]}
    monkeypatch.setattr(api, "_owner_command", command)
    with client() as connection:
        listed = connection.get("/api/browser-sessions").json()["sessions"][0]
    assert listed["location"] == location
    assert "runtime" not in listed and "10.0.0.5" not in json.dumps(listed)


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


class FakeAssist:
    TOKEN_HEADER = "X-Assist-Token"
    WS_PATH_HEADER = "X-Assist-Ws"

    def __init__(self, state: dict[str, Any] | None = None):
        self.state, self.calls = state, []

    def running(self, name):
        self.calls.append(("running", name))
        return self.state

    def ensure(self, name, actor, **kwargs):
        self.calls.append(("ensure", name, actor, kwargs))
        self.state = {"name": name, "port": 4555, "token": "tok"}
        return {"started": True, "window": False}

    def stop(self, name):
        self.calls.append(("stop", name))

    def render_page(self, config):
        return f"<p>{json.dumps(config)}</p>"


def assist_fixture(monkeypatch, state=None, current=None):
    fake = FakeAssist(state)
    monkeypatch.setattr(api, "_assist", lambda: fake)
    monkeypatch.setattr(api, "_st_cli_path", lambda: "/bin/st")
    async def command(args, actor=None):
        fake.calls.append(("owner", args, actor))
        return {"schema_version": 1, "sessions": [current or session()]}
    monkeypatch.setattr(api, "_owner_command", command)
    requests = []
    def handler(request):
        requests.append(request)
        return api.httpx.Response(200, text="<p>assist page</p>")
    real = api.httpx.AsyncClient
    monkeypatch.setattr(api.httpx, "AsyncClient", lambda **kw: real(transport=api.httpx.MockTransport(handler), **kw))
    return fake, requests


def test_assist_page_starts_on_demand_without_a_window_and_proxies_with_the_token(monkeypatch) -> None:
    fake, requests = assist_fixture(monkeypatch)
    monkeypatch.setattr(api.agent_sessions, "pause_reason", lambda _name: "login needed: example.com")
    with client() as connection:
        response = connection.get("/api/browser-assist/agent-a")
    assert response.status_code == 200 and response.text == "<p>assist page</p>"
    assert response.headers["cache-control"] == "no-store"
    ensure = next(call for call in fake.calls if call[0] == "ensure")
    assert ensure[1:3] == ("agent-a", "agent:one")
    assert ensure[3]["window"] is False and ensure[3]["reason"] == "login needed: example.com"
    assert str(requests[0].url) == "http://127.0.0.1:4555/"
    assert requests[0].headers["x-assist-token"] == "tok"
    assert requests[0].headers["x-assist-ws"] == "/ws/browser-assist/agent-a"


def test_assist_page_says_nothing_waits_for_an_unpaused_session(monkeypatch) -> None:
    fake, requests = assist_fixture(monkeypatch, current=session(paused=False))
    with client() as connection:
        response = connection.get("/api/browser-assist/agent-a")
    assert response.status_code == 200 and '"waiting": false' in response.text
    assert requests == [] and not any(call[0] == "ensure" for call in fake.calls)


def test_assist_page_requires_owner(monkeypatch) -> None:
    fake, _requests = assist_fixture(monkeypatch)
    with client(role="viewer") as connection:
        assert connection.get("/api/browser-assist/agent-a").status_code == 403
    assert fake.calls == []


@pytest.mark.parametrize(("action", "stops"), [("resume", True), ("close", True), ("pause", False)])
def test_lifecycle_changes_end_an_open_assist_window_first(monkeypatch, action, stops) -> None:
    fake, _requests = assist_fixture(monkeypatch)
    with client() as connection:
        response = connection.post(f"/api/browser-sessions/agent-a/{action}", json={"actor": "agent:one"},
                                   headers={"Origin": "http://testserver"})
    assert response.status_code == 200
    names = [call[0] if call[0] != "owner" else call[1][0] for call in fake.calls]
    assert names == (["list", "stop", action, "list"] if stops else ["list", action, "list"])


class Upstream:
    def __init__(self):
        self.sent: list[str] = []
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_args):
        return None
    async def send(self, raw):
        self.sent.append(raw)
    async def __aiter__(self):
        yield json.dumps({"type": "hello"})
        await asyncio.sleep(0.2)


@pytest.mark.parametrize("origin", [None, "https://other.test"])
def test_assist_socket_authenticates_and_checks_actual_origin(monkeypatch, origin) -> None:
    assist_fixture(monkeypatch, state={"port": 4555, "token": "tok"})
    monkeypatch.setattr(api, "resolve_principal", lambda _request: AccessPrincipal("operator@example.test", "owner", True))
    monkeypatch.setattr(api, "connect", lambda *a, **kw: pytest.fail("no upstream before authorization"))
    headers = {"Origin": origin} if origin else {}
    with client() as connection, pytest.raises(WebSocketDisconnect), \
            connection.websocket_connect("/ws/browser-assist/agent-a", headers=headers) as ws:
        ws.receive_text()


def test_assist_socket_relays_to_the_token_holding_server(monkeypatch) -> None:
    assist_fixture(monkeypatch, state={"port": 4555, "token": "tok"})
    monkeypatch.setattr(api, "resolve_principal", lambda _request: AccessPrincipal("operator@example.test", "owner", True))
    upstream = Upstream()
    def connect(url, **kwargs):
        assert url == "ws://127.0.0.1:4555/ws"
        assert kwargs["additional_headers"] == {"X-Assist-Token": "tok"} and kwargs["proxy"] is None
        return upstream
    monkeypatch.setattr(api, "connect", connect)
    with client() as connection, \
            connection.websocket_connect("/ws/browser-assist/agent-a", headers={"Origin": "http://testserver"}) as ws:
        assert json.loads(ws.receive_text()) == {"type": "hello"}
        ws.send_text('{"type":"done"}')
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()
    assert upstream.sent == ['{"type":"done"}']
