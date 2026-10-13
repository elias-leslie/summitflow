"""Authenticated Runtime adapter to browser-owned sessions and their assist window.

Session storage, actor authority, launch, locks and the live view remain in the
browser-automation owner. Its assist window (live page plus Done/Approve/Decline)
runs on loopback only while a session waits; this module proxies it for remote
owners behind Cloudflare Access and never records frames or input.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
from typing import Annotated, Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from cli.lib import browser_agent_sessions as agent_sessions

from ..access_control import AccessPrincipal, resolve_principal
from ..utils.safe_subprocess import run_async
from .backups.key_endpoints import _require_same_origin
from .docker._runtime_control import _st_cli_path
from .monitor import require_monitor_owner

router = APIRouter(tags=["runtime"])
Owner = Annotated[AccessPrincipal, Depends(require_monitor_owner)]


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


def _public_session(value: dict[str, Any]) -> dict[str, Any]:
    if not all(isinstance(value.get(key), str) and value[key] for key in ("name", "actor", "state")):
        raise HTTPException(503, "Browser session owner returned an invalid session")
    if not isinstance(value.get("paused"), bool):
        raise HTTPException(503, "Browser session owner returned an invalid pause state")
    public = {key: value.get(key) for key in (
        "name", "actor", "state", "paused", "runtime_state", "last_used_ms",
    )}
    public["location"] = _location(value.get("runtime"))
    # The agent's reason for handing over ("login needed: <site>"), shown to the owner only.
    public["pause_reason"] = agent_sessions.pause_reason(value["name"]) if value.get("paused") else None
    return public


def _location(runtime: Any) -> str | None:
    """Where the session's browser runs, without exposing the VM endpoint."""
    target = runtime.get("target") if isinstance(runtime, dict) else None
    return {"proxmox": "proxmox", "local-ai": "local"}.get(target) if isinstance(target, str) else None


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
    if action != "pause":
        # An open assist window holds the human lease; end it before the change.
        await asyncio.to_thread(_assist().stop, name)
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


def _assist() -> Any:
    return agent_sessions._assist()


async def _assist_server(name: str) -> dict[str, Any] | None:
    """NAME's assist server, started on demand while the session waits for the owner."""
    assist = _assist()
    try:
        state = await asyncio.to_thread(assist.running, name)
    except ValueError:
        return None
    if state:
        return state
    inventory = await _owner_command(["list", "--all"])
    listed = inventory.get("sessions")
    sessions: list[Any] = listed if isinstance(listed, list) else []
    session = next((_public_session(item) for item in sessions if isinstance(item, dict) and item.get("name") == name), None)
    if session is None or not session["paused"] or session["state"] in {"closed", "revoked"}:
        return None
    try:
        await asyncio.to_thread(assist.ensure, name, session["actor"], reason=session["pause_reason"] or "",
                                window=False, st_bin=str(_st_cli_path()))
    except ValueError as exc:
        raise HTTPException(503, "Assist window is unavailable") from exc
    return await asyncio.to_thread(assist.running, name)


@router.get("/api/browser-assist/{name}", response_class=HTMLResponse)
async def assist_page(name: str, _owner: Owner) -> HTMLResponse:
    headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
    state = await _assist_server(name)
    if state is None:
        return HTMLResponse(_assist().render_page({"waiting": False, "name": name}), headers=headers)
    assist = _assist()
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        try:
            page = await client.get(f"http://127.0.0.1:{state['port']}/", headers={
                assist.TOKEN_HEADER: state["token"], assist.WS_PATH_HEADER: f"/ws/browser-assist/{quote(name, safe='')}"})
        except httpx.HTTPError as exc:
            raise HTTPException(503, "Assist window is unavailable") from exc
    if page.status_code != 200:
        raise HTTPException(503, "Assist window is unavailable")
    return HTMLResponse(page.text, headers=headers)


@router.websocket("/ws/browser-assist/{name}")
async def assist_socket(ws: WebSocket, name: str) -> None:
    """Byte relay to the assist server; it validates input and owns the lease."""
    try:
        _authorize_stream(ws)
        state = await asyncio.to_thread(_assist().running, name)
        if not state:
            raise HTTPException(409, "Session is not waiting for the owner")
        async with connect(f"ws://127.0.0.1:{state['port']}/ws", max_size=8 * 1024 * 1024, open_timeout=5,
                           close_timeout=5, proxy=None,
                           additional_headers={_assist().TOKEN_HEADER: state["token"]}) as upstream:
            await ws.accept()

            async def down() -> None:
                async for raw in upstream:
                    await ws.send_text(raw if isinstance(raw, str) else raw.decode())

            async def up() -> None:
                while True:
                    await upstream.send(await ws.receive_text())

            tasks = [asyncio.create_task(down()), asyncio.create_task(up())]
            _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await ws.close(code=1000)
    except (HTTPException, ValueError, OSError, TimeoutError, WebSocketException, RuntimeError):
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await ws.close(code=1008, reason="Assist window ended")
    except WebSocketDisconnect:
        pass
