"""Authenticated Runtime adapter to browser-owned sessions and native streaming.

Session storage, actor authority, launch and locks remain in the extension owner.
Frames and human input are relayed in memory only, never recorded or logged here.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import subprocess
from typing import Annotated, Any, cast
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket
from pydantic import BaseModel, ConfigDict, Field
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from ..access_control import AccessPrincipal, resolve_principal
from ..utils.safe_subprocess import PipeProcess, run_async, spawn_duplex
from .backups.key_endpoints import _require_same_origin
from .docker._runtime_control import _st_cli_path
from .monitor import require_monitor_owner

router = APIRouter(tags=["runtime"])
Owner = Annotated[AccessPrincipal, Depends(require_monitor_owner)]
# Transport lifetime only; the extension remains the session authority/store.
_connections: dict[tuple[str, str], list[tuple[WebSocket, asyncio.Event, asyncio.Event]]] = {}


async def _owner_command(args: list[str], actor: str | None = None) -> dict[str, Any]:
    env = dict(os.environ)
    if actor is not None:
        env["ST_BROWSER_OWNER"] = actor
    try:
        result = await run_async(
            [str(_st_cli_path()), "--no-compact", "browser", "--local-ai", "session", *args],
            env=env, capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(503, "Browser session owner is unavailable") from exc
    if result.returncode:
        # Owner diagnostics can contain page data. Keep API errors predictable.
        raise HTTPException(409, "Browser session operation was rejected; refresh its state")
    try:
        # Legacy cleanup diagnostics may precede the owner JSON line. Never
        # expose them through Runtime or treat an earlier line as a response.
        value = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, TypeError, IndexError) as exc:
        raise HTTPException(503, "Browser session owner returned an invalid response") from exc
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise HTTPException(503, "Browser session owner response is incompatible")
    return value


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


def _display_url(value: object) -> str:
    """Human display never carries OAuth queries, fragments or URL credentials."""
    if not isinstance(value, str):
        return ""
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https", "about"}:
            return ""
        authority = parts.netloc.rsplit("@", 1)[-1]
        return urlunsplit((parts.scheme, authority, parts.path, "", ""))
    except ValueError:
        return ""


def _display_page(value: object) -> dict[str, str]:
    page = cast(dict[str, object], value) if isinstance(value, dict) else {}
    title = page.get("title")
    return {"url": _display_url(page.get("url")),
            "title": title if isinstance(title, str) else "Selected browser target"}


def _public_session(value: dict[str, Any]) -> dict[str, Any]:
    if not all(isinstance(value.get(key), str) and value[key] for key in ("name", "actor", "state")):
        raise HTTPException(503, "Browser session owner returned an invalid session")
    if not isinstance(value.get("paused"), bool):
        raise HTTPException(503, "Browser session owner returned an invalid pause state")
    return {key: value.get(key) for key in (
        "name", "actor", "state", "paused", "runtime_state", "last_used_ms",
    )}


async def _selected(name: str, actor: str) -> dict[str, Any]:
    inventory = await _owner_command(["list", "--all"])
    sessions = inventory.get("sessions")
    if not isinstance(sessions, list):
        raise HTTPException(503, "Browser session inventory is invalid")
    for candidate in sessions:
        if isinstance(candidate, dict) and candidate.get("name") == name:
            session = _public_session(candidate)
            if session["actor"] != actor:
                raise HTTPException(409, "Session owner changed; select the session again")
            return session
    raise HTTPException(409, "Selected session is no longer available")


class SessionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: str = Field(min_length=1, max_length=256)


@router.get("/api/browser-sessions")
async def list_sessions(_owner: Owner, response: Response) -> dict[str, Any]:
    _private(response)
    value = await _owner_command(["list", "--all"])
    sessions = value.get("sessions")
    if not isinstance(sessions, list) or not all(isinstance(item, dict) for item in sessions):
        raise HTTPException(503, "Browser session inventory is invalid")
    return {"schema_version": 1, "sessions": [_public_session(item) for item in sessions]}


@router.post("/api/browser-sessions/{name}/{action}")
async def change_session(
    name: str, action: str, selection: SessionSelection,
    request: Request, response: Response, _owner: Owner,
) -> dict[str, Any]:
    _require_same_origin(request)
    _private(response)
    if action not in {"pause", "resume", "close"}:
        raise HTTPException(404, "Unknown browser session action")
    selected = await _selected(name, selection.actor)
    if selected["state"] in {"closed", "revoked"}:
        raise HTTPException(409, "Selected session is closed")
    for socket, released, stop in tuple(_connections.get((name, selection.actor), [])):
        stop.set()
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await socket.close(code=1000, reason="Operator changed selected session state")
        try:
            await asyncio.wait_for(released.wait(), timeout=12)
        except TimeoutError as exc:
            raise HTTPException(409, "Live view is still disconnecting; refresh its state") from exc
    await _owner_command([action, name], actor=selected["actor"])
    return {"schema_version": 1, "session": await _selected(name, selection.actor)}


def _web_request(ws: WebSocket) -> Request:
    scope = {**ws.scope, "type": "http", "method": "GET",
             "scheme": "https" if ws.url.scheme == "wss" else "http",
             "headers": [(key, value) for key, value in ws.scope["headers"] if key != b"sec-fetch-site"]}
    return Request(scope)


def _authorize_stream(ws: WebSocket) -> AccessPrincipal:
    request = _web_request(ws)
    # WebSocket scopes do not pass through the HTTP access-control middleware.
    request.state.principal = resolve_principal(request)
    principal = require_monitor_owner(request)
    if not request.headers.get("origin"):
        raise HTTPException(403, "Same-origin browser stream required")
    _require_same_origin(request)
    return principal


def _paused(value: dict[str, Any], name: str, actor: str) -> None:
    if (value.get("name") != name or value.get("actor") != actor
            or value.get("paused") is not True or value.get("state") in {"closed", "revoked"}):
        raise HTTPException(409, "Session is no longer paused for this owner")


def _view_binding(value: dict[str, Any], name: str, actor: str) -> tuple[int, dict[str, Any]]:
    _paused(value, name, actor)
    stream, binding = value.get("stream"), value.get("binding")
    if (not isinstance(stream, dict) or stream.get("enabled") is not True
            or type(stream.get("port")) is not int or not 1 <= stream["port"] <= 65535
            or not isinstance(binding, dict) or binding.get("session") != name
            or not all(isinstance(binding.get(key), str) and binding[key]
                       for key in ("target_id", "document_id"))):
        raise HTTPException(409, "Selected session has no live target")
    return stream["port"], binding


def _input_event(raw: str) -> dict[str, Any]:
    """Only native input and frame acknowledgements; no commands or target changes."""
    if len(raw) > 4096:
        raise ValueError("Input message is too large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Invalid native input")
    kind = value.get("type")
    if kind == "release" and set(value) == {"type"}:
        return value
    if kind == "ack" and set(value) == {"type", "seq"} and type(value["seq"]) is int and value["seq"] >= 0:
        return value
    if kind == "input_mouse":
        allowed = {"type", "eventType", "x", "y", "button", "clickCount", "deltaX", "deltaY", "modifiers"}
        if value.get("eventType") not in {"mousePressed", "mouseReleased", "mouseMoved", "mouseWheel"}:
            raise ValueError("Invalid mouse event")
        if value.get("button", "none") not in {"none", "left", "middle", "right"}:
            raise ValueError("Invalid mouse button")
        for field in ("x", "y"):
            if type(value.get(field)) not in {int, float} or not math.isfinite(value[field]) or not 0 <= value[field] <= 100000:
                raise ValueError("Invalid mouse position")
        for field in ("deltaX", "deltaY", "clickCount", "modifiers"):
            number = value.get(field, 0)
            if type(number) not in {int, float} or not math.isfinite(number) or abs(number) > 100000:
                raise ValueError("Invalid mouse input")
        if type(value.get("clickCount", 0)) is not int or not 0 <= value.get("clickCount", 0) <= 3:
            raise ValueError("Invalid mouse click count")
        if type(value.get("modifiers", 0)) is not int or not 0 <= value.get("modifiers", 0) <= 15:
            raise ValueError("Invalid mouse modifiers")
    elif kind == "input_keyboard":
        allowed = {"type", "eventType", "key", "code", "text", "windowsVirtualKeyCode", "modifiers"}
        if value.get("eventType") not in {"keyDown", "keyUp", "char"}:
            raise ValueError("Invalid keyboard event")
        for field in ("key", "code", "text"):
            if field in value and (not isinstance(value[field], str) or len(value[field]) > 64):
                raise ValueError("Invalid keyboard input")
        for field in ("windowsVirtualKeyCode", "modifiers"):
            if field in value and (type(value[field]) is not int or not 0 <= value[field] <= 65535):
                raise ValueError("Invalid keyboard input")
        if value.get("modifiers", 0) > 15:
            raise ValueError("Invalid keyboard modifiers")
    else:
        raise ValueError("Unsupported native input")
    if set(value) - allowed:
        raise ValueError("Unknown native input field")
    return value


async def _release_lease(process: PipeProcess) -> None:
    process.close_stdin()
    # Poll rather than cancelling a to_thread(waitpid), which could leave two
    # waiters racing to reap the same process during shutdown.
    for _ in range(100):
        if process.poll() is not None:
            process.close()
            return
        await asyncio.sleep(0.05)
    process.terminate()  # ST forwards termination to its owner process group.
    for _ in range(100):
        if process.poll() is not None:
            process.close()
            return
        await asyncio.sleep(0.05)
    process.kill()
    await process.wait()
    process.close()


@router.websocket("/ws/browser-sessions/{name}")
async def live_session(ws: WebSocket, name: str) -> None:
    tasks: list[asyncio.Task[None]] = []
    lease: PipeProcess | None = None
    registration: tuple[WebSocket, asyncio.Event, asyncio.Event] | None = None
    actor = ws.query_params.get("actor", "")
    try:
        principal = _authorize_stream(ws)
        selected = await _selected(name, actor)
        _paused(selected, name, actor)
        registration = (ws, asyncio.Event(), asyncio.Event())
        _connections.setdefault((name, actor), []).append(registration)
        env = {**os.environ, "ST_BROWSER_OWNER": actor}
        lease = spawn_duplex([
            str(_st_cli_path()), "--no-compact", "browser", "--local-ai", "session", "lease", name,
        ], env=env)
        ready = await asyncio.wait_for(lease.readline(), timeout=20)
        view = json.loads(ready)
        if (not isinstance(view, dict) or type(view.get("schema_version")) is not int
                or view["schema_version"] != 1 or view.get("status") != "leased"):
            raise HTTPException(409, "Browser human lease is unavailable")
        port, binding = _view_binding(view, name, actor)
        async with connect(f"ws://127.0.0.1:{port}/?pacing=ack&maxFps=15", max_size=8 * 1024 * 1024,
                           open_timeout=5, close_timeout=5, proxy=None) as upstream:
            await ws.accept()
            await upstream.send(json.dumps({"type": "config", "pacing": "ack", "maxFps": 15}))
            await ws.send_json({"type": "bound", "binding": binding, "page": _display_page(view.get("page"))})

            async def verify() -> None:
                current = _authorize_stream(ws)
                if current.email != principal.email:
                    raise HTTPException(403, "Operator identity changed")
                if lease is None or lease.poll() is not None:
                    raise HTTPException(409, "Browser human lease ended")

            async def input_loop() -> None:
                while True:
                    event = _input_event(await ws.receive_text())
                    await verify()
                    if event["type"] == "release":
                        return
                    await upstream.send(json.dumps(event))
                    if event["type"] != "ack":
                        await ws.send_json({"type": "input_forwarded"})

            async def frame_loop() -> None:
                async for raw in upstream:
                    value = json.loads(raw)
                    if isinstance(value, dict) and value.get("type") == "frame":
                        await ws.send_text(raw if isinstance(raw, str) else raw.decode())
                    elif isinstance(value, dict) and value.get("type") == "tabs":
                        tabs = value.get("tabs")
                        if not isinstance(tabs, list):
                            raise ValueError("Invalid stream target inventory")
                        active = [tab for tab in tabs if isinstance(tab, dict) and tab.get("active") is True]
                        if len(active) != 1 or active[0].get("targetId") != binding["target_id"]:
                            raise HTTPException(409, "Selected browser target changed")
                    elif isinstance(value, dict) and value.get("type") == "url":
                        # Same target may navigate during human sign-in. Surface
                        # its current URL without changing targets or launching.
                        await ws.send_json({"type": "url", "url": _display_url(value.get("url"))})

            async def authority_loop() -> None:
                while True:
                    await asyncio.sleep(2)
                    await verify()

            async def control_loop() -> None:
                if registration is not None:
                    await registration[2].wait()

            tasks = [asyncio.create_task(loop()) for loop in (input_loop, frame_loop, authority_loop, control_loop)]
            done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            # The owning client needs proof of owner EOF/reap before sending
            # lifecycle HTTP to any worker. Stop all forwarding first.
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            tasks = []
            # Close the ordered input channel before unlocking the owner so
            # queued human input cannot race newly resumed agent commands.
            await upstream.close()
            await _release_lease(lease)
            lease = None
            await ws.send_json({"type": "released"})
            await ws.close(code=1000, reason="Browser stream ended")
    except (HTTPException, ValueError, OSError, TimeoutError, WebSocketException, RuntimeError):
        # Do not include page content, input, actor or upstream URLs in errors/logs.
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await ws.close(code=1008, reason="Live view ended; refresh the selected session")
    except WebSocketDisconnect:
        pass
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if lease is not None:
            await _release_lease(lease)
        if registration is not None:
            registration[1].set()
            connections = _connections.get((name, actor), [])
            if registration in connections:
                connections.remove(registration)
            if not connections:
                _connections.pop((name, actor), None)
