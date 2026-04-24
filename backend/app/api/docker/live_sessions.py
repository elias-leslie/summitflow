"""Operator-visible browser co-driving sessions for runtime work."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import quote

import httpx
import websockets
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from ...utils.env import float_env
from .helpers import _require_auth

LiveSessionKind = Literal["browser"]
LiveSessionState = Literal["active", "expired", "closed"]
LiveControlAction = Literal["click", "key", "text", "wheel", "navigate", "resize"]
LiveAuditActor = Literal["internal", "operator"]

_DEFAULT_BROWSER_HOST = "127.0.0.1"
_DEFAULT_BROWSER_PORT = 9222
_DEFAULT_TARGET_URL = "https://www.amazon.com/photos/all"
_SESSION_TTL_SECONDS = int(float_env("SUMMITFLOW_LIVE_SESSION_TTL_SECONDS", 30 * 60))
_CDP_HTTP_TIMEOUT_SECONDS = float_env("SUMMITFLOW_LIVE_CDP_HTTP_TIMEOUT", 5.0)
_CDP_WS_TIMEOUT_SECONDS = float_env("SUMMITFLOW_LIVE_CDP_WS_TIMEOUT", 8.0)
_SCREENSHOT_QUALITY = 68
_MAX_VIEWPORT_WIDTH = 3840
_MAX_VIEWPORT_HEIGHT = 2160
_MAX_TEXT_INPUT_CHARS = 4096
_MAX_SECURE_TEXT_INPUT_BYTES = 16 * 1024
_EDITABLE_FOCUS_EXPRESSION = """
(() => {
  const blockedInputTypes = new Set([
    'button',
    'checkbox',
    'color',
    'file',
    'hidden',
    'image',
    'radio',
    'range',
    'reset',
    'submit',
  ]);
  function activeElement(root) {
    const active = root && root.activeElement;
    if (active && active.tagName === 'IFRAME') {
      try {
        return activeElement(active.contentDocument) || active;
      } catch {
        return active;
      }
    }
    return active;
  }
  function isEditable(element) {
    if (!element) return false;
    if (element.isContentEditable) return true;
    if (element.disabled || element.readOnly) return false;
    const tagName = element.tagName;
    if (tagName === 'TEXTAREA') return true;
    if (tagName !== 'INPUT') return false;
    const type = (element.getAttribute('type') || 'text').toLowerCase();
    return !blockedInputTypes.has(type);
  }
  return isEditable(activeElement(document));
})()
"""

router = APIRouter(dependencies=[Depends(_require_auth)])


class LiveSessionCreate(BaseModel):
    """Request to create an operator-visible live session."""

    kind: LiveSessionKind = "browser"
    target_url: str = _DEFAULT_TARGET_URL
    viewport_width: int = Field(default=1440, ge=640, le=_MAX_VIEWPORT_WIDTH)
    viewport_height: int = Field(default=900, ge=360, le=_MAX_VIEWPORT_HEIGHT)


class LiveSessionStatus(BaseModel):
    """Public status for a live co-driving session."""

    id: str
    kind: LiveSessionKind
    state: LiveSessionState
    target_url: str
    current_url: str | None = None
    title: str | None = None
    sensitive: bool
    created_at: datetime
    expires_at: datetime
    viewport_width: int
    viewport_height: int
    control_enabled: bool
    control_owner: str | None = None
    viewer_connected: bool
    token_required: bool
    last_viewed_at: datetime | None = None
    last_controlled_at: datetime | None = None
    audit_events: list[LiveSessionAuditEvent]
    control_policy: str
    capture_policy: str


class LiveSessionCreated(LiveSessionStatus):
    """Create response with the one-time operator token."""

    operator_token: str


class LiveSessionAuditEvent(BaseModel):
    """Sanitized session audit event."""

    at: datetime
    actor: LiveAuditActor
    action: str
    detail: str | None = None


class LiveSessionFrame(BaseModel):
    """Screenshot frame for a live session."""

    session_id: str
    captured_at: datetime
    image_data_url: str
    viewport_width: int
    viewport_height: int
    sensitive: bool


class LiveSessionControl(BaseModel):
    """Remote control command for a live session."""

    action: LiveControlAction
    x: int | None = Field(default=None, ge=0, le=_MAX_VIEWPORT_WIDTH)
    y: int | None = Field(default=None, ge=0, le=_MAX_VIEWPORT_HEIGHT)
    key: str | None = Field(default=None, max_length=32)
    text: str | None = None
    delta_x: int | None = Field(default=0, ge=-4000, le=4000)
    delta_y: int | None = Field(default=0, ge=-4000, le=4000)
    target_url: str | None = Field(default=None, max_length=2048)
    viewport_width: int | None = Field(default=None, ge=640, le=_MAX_VIEWPORT_WIDTH)
    viewport_height: int | None = Field(default=None, ge=360, le=_MAX_VIEWPORT_HEIGHT)


class LiveSessionSensitiveUpdate(BaseModel):
    """Toggle sensitive handling for auth flows."""

    sensitive: bool


class LiveSessionControlGrantUpdate(BaseModel):
    """Toggle operator input control."""

    enabled: bool


@dataclass(slots=True)
class _ManagedLiveSession:
    id: str
    kind: LiveSessionKind
    target_url: str
    target_id: str
    ws_url: str
    operator_token_hash: str
    created_at: datetime
    expires_at: datetime
    viewport_width: int
    viewport_height: int
    sensitive: bool = True
    control_enabled: bool = False
    viewer_connected: bool = False
    last_viewed_at: datetime | None = None
    last_controlled_at: datetime | None = None
    audit_events: list[LiveSessionAuditEvent] | None = None
    state: LiveSessionState = "active"
    current_url: str | None = None
    title: str | None = None


_LIVE_SESSIONS: dict[str, _ManagedLiveSession] = {}
_LIVE_SESSION_LOCK = asyncio.Lock()


@router.get("", response_model=list[LiveSessionStatus])
async def list_live_sessions() -> list[LiveSessionStatus]:
    """List active operator-visible sessions."""
    await _cleanup_expired_sessions()
    return [_status_from_session(session) for session in _LIVE_SESSIONS.values()]


@router.post("", response_model=LiveSessionCreated)
async def create_live_session(payload: LiveSessionCreate) -> LiveSessionCreated:
    """Create a browser co-driving session through the internal CDP broker."""
    _validate_target_url(payload.target_url)
    if payload.kind != "browser":
        raise HTTPException(status_code=400, detail="Only browser sessions are supported")

    session_id = secrets.token_urlsafe(10)
    operator_token = secrets.token_urlsafe(32)
    target = await _create_browser_target(payload.target_url)
    session = _ManagedLiveSession(
        id=session_id,
        kind=payload.kind,
        target_url=payload.target_url,
        target_id=target["id"],
        ws_url=target["webSocketDebuggerUrl"],
        operator_token_hash=_token_hash(operator_token),
        created_at=_now(),
        expires_at=_now() + timedelta(seconds=_SESSION_TTL_SECONDS),
        viewport_width=payload.viewport_width,
        viewport_height=payload.viewport_height,
        audit_events=[],
    )
    _audit(session, actor="internal", action="created")
    await _configure_viewport(session)

    async with _LIVE_SESSION_LOCK:
        _LIVE_SESSIONS[session.id] = session
    await _refresh_page_metadata(session)
    return LiveSessionCreated(**_status_from_session(session).model_dump(), operator_token=operator_token)


@router.get("/{session_id}", response_model=LiveSessionStatus)
async def get_live_session(session_id: str) -> LiveSessionStatus:
    """Get one live session status."""
    session = await _require_session(session_id)
    await _refresh_page_metadata(session)
    return _status_from_session(session)


@router.get("/{session_id}/frame", response_model=LiveSessionFrame)
async def get_live_session_frame(
    session_id: str,
    x_live_session_token: str = Header(default=""),
) -> LiveSessionFrame:
    """Capture the current browser frame without exposing CDP to the frontend."""
    session = await _require_session(session_id)
    actor = _require_view_authorization(session, x_live_session_token)
    await _cdp_call(session.ws_url, "Page.bringToFront")
    result = await _cdp_call(
        session.ws_url,
        "Page.captureScreenshot",
        {
            "format": "jpeg",
            "quality": _SCREENSHOT_QUALITY,
            "fromSurface": True,
            "captureBeyondViewport": False,
        },
    )
    image = result.get("data")
    if not isinstance(image, str) or not image:
        raise HTTPException(status_code=502, detail="Browser did not return a frame")
    now = _now()
    session.viewer_connected = True
    session.last_viewed_at = now
    _audit(session, actor=actor, action="viewed")
    return LiveSessionFrame(
        session_id=session.id,
        captured_at=now,
        image_data_url=f"data:image/jpeg;base64,{image}",
        viewport_width=session.viewport_width,
        viewport_height=session.viewport_height,
        sensitive=session.sensitive,
    )


@router.post("/{session_id}/control", response_model=LiveSessionStatus)
async def control_live_session(
    session_id: str,
    payload: LiveSessionControl,
    x_live_session_token: str = Header(default=""),
) -> LiveSessionStatus:
    """Send an operator control command through the internal CDP broker."""
    session = await _require_session(session_id)
    _require_operator_token(session, x_live_session_token)
    if not session.control_enabled:
        raise HTTPException(status_code=423, detail="Input control is not enabled")
    await _apply_control(session, payload)
    session.last_controlled_at = _now()
    _audit(session, actor="operator", action=f"control:{payload.action}")
    await _refresh_page_metadata(session)
    return _status_from_session(session)


@router.post("/{session_id}/secure-text", response_model=LiveSessionStatus)
async def secure_text_live_session(
    session_id: str,
    request: Request,
    x_live_session_token: str = Header(default=""),
) -> LiveSessionStatus:
    """Relay sensitive text without JSON validation echoes."""
    session = await _require_session(session_id)
    _require_operator_token(session, x_live_session_token)
    if not session.control_enabled:
        raise HTTPException(status_code=423, detail="Input control is not enabled")
    text = await _read_secure_text_body(request)
    await _insert_text(session, text, require_editable=True)
    session.last_controlled_at = _now()
    _audit(session, actor="operator", action="control:text")
    await _refresh_page_metadata(session)
    return _status_from_session(session)


@router.post("/{session_id}/sensitive", response_model=LiveSessionStatus)
async def update_live_session_sensitive(
    session_id: str,
    payload: LiveSessionSensitiveUpdate,
    x_live_session_token: str = Header(default=""),
) -> LiveSessionStatus:
    """Toggle sensitive mode for auth or account views."""
    session = await _require_session(session_id)
    _require_operator_token(session, x_live_session_token)
    session.sensitive = payload.sensitive
    _audit(
        session,
        actor="operator",
        action="sensitive-enabled" if payload.sensitive else "sensitive-disabled",
    )
    return _status_from_session(session)


@router.post("/{session_id}/control-grant", response_model=LiveSessionStatus)
async def update_live_session_control_grant(
    session_id: str,
    payload: LiveSessionControlGrantUpdate,
    x_live_session_token: str = Header(default=""),
) -> LiveSessionStatus:
    """Toggle operator input control for a session."""
    session = await _require_session(session_id)
    _require_operator_token(session, x_live_session_token)
    session.control_enabled = payload.enabled
    _audit(
        session,
        actor="operator",
        action="control-enabled" if payload.enabled else "control-disabled",
    )
    return _status_from_session(session)


@router.post("/{session_id}/teardown", response_model=LiveSessionStatus)
async def teardown_live_session(session_id: str) -> LiveSessionStatus:
    """Close a live session and its browser target."""
    session = await _require_session(session_id)
    _audit(session, actor="internal", action="teardown")
    await _close_session(session)
    async with _LIVE_SESSION_LOCK:
        _LIVE_SESSIONS.pop(session.id, None)
    return _status_from_session(session)


async def _apply_control(session: _ManagedLiveSession, payload: LiveSessionControl) -> None:
    if payload.action == "text":
        if payload.text is None:
            raise HTTPException(status_code=400, detail="text is required")
        _validate_text_input(payload.text)
    await _cdp_call(session.ws_url, "Page.bringToFront")
    if payload.action == "click":
        await _dispatch_click(session, payload)
        return
    if payload.action == "key":
        await _dispatch_key(session, payload)
        return
    if payload.action == "text":
        text = payload.text
        if text is None:
            raise HTTPException(status_code=400, detail="text is required")
        await _insert_text(session, text, bring_to_front=False)
        return
    if payload.action == "wheel":
        await _dispatch_wheel(session, payload)
        return
    if payload.action == "navigate":
        if payload.target_url is None:
            raise HTTPException(status_code=400, detail="target_url is required")
        _validate_target_url(payload.target_url)
        session.target_url = payload.target_url
        await _cdp_call(session.ws_url, "Page.navigate", {"url": payload.target_url})
        return
    if payload.action == "resize":
        if payload.viewport_width is None or payload.viewport_height is None:
            raise HTTPException(status_code=400, detail="viewport size is required")
        session.viewport_width = payload.viewport_width
        session.viewport_height = payload.viewport_height
        await _configure_viewport(session)


async def _read_secure_text_body(request: Request) -> str:
    raw = await request.body()
    if len(raw) > _MAX_SECURE_TEXT_INPUT_BYTES:
        raise HTTPException(status_code=413, detail="Secure text is too long")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Secure text must be UTF-8") from exc
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    _validate_text_input(text)
    return text


async def _insert_text(
    session: _ManagedLiveSession,
    text: str,
    *,
    bring_to_front: bool = True,
    require_editable: bool = False,
) -> None:
    _validate_text_input(text)
    if bring_to_front:
        await _cdp_call(session.ws_url, "Page.bringToFront")
    if require_editable and not await _has_focused_editable(session):
        raise HTTPException(status_code=409, detail="No focused text field")
    await _cdp_call(session.ws_url, "Input.insertText", {"text": text})


def _validate_text_input(text: str) -> None:
    if len(text) > _MAX_TEXT_INPUT_CHARS:
        raise HTTPException(status_code=413, detail="Text input is too long")


async def _has_focused_editable(session: _ManagedLiveSession) -> bool:
    result = await _cdp_call(
        session.ws_url,
        "Runtime.evaluate",
        {
            "expression": _EDITABLE_FOCUS_EXPRESSION,
            "returnByValue": True,
        },
    )
    return result.get("result", {}).get("value") is True


async def _dispatch_click(session: _ManagedLiveSession, payload: LiveSessionControl) -> None:
    if payload.x is None or payload.y is None:
        raise HTTPException(status_code=400, detail="x and y are required")
    await _cdp_call(
        session.ws_url,
        "Input.dispatchMouseEvent",
        {
            "type": "mousePressed",
            "x": payload.x,
            "y": payload.y,
            "button": "left",
            "clickCount": 1,
        },
    )
    await _cdp_call(
        session.ws_url,
        "Input.dispatchMouseEvent",
        {
            "type": "mouseReleased",
            "x": payload.x,
            "y": payload.y,
            "button": "left",
            "clickCount": 1,
        },
    )


async def _dispatch_wheel(session: _ManagedLiveSession, payload: LiveSessionControl) -> None:
    await _cdp_call(
        session.ws_url,
        "Input.dispatchMouseEvent",
        {
            "type": "mouseWheel",
            "x": payload.x or 0,
            "y": payload.y or 0,
            "deltaX": payload.delta_x or 0,
            "deltaY": payload.delta_y or 0,
        },
    )


async def _dispatch_key(session: _ManagedLiveSession, payload: LiveSessionControl) -> None:
    key = payload.key
    if not key:
        raise HTTPException(status_code=400, detail="key is required")
    key_code = _KEY_CODES.get(key, 0)
    params: dict[str, Any] = {"key": key}
    if key_code:
        params["windowsVirtualKeyCode"] = key_code
        params["nativeVirtualKeyCode"] = key_code
    await _cdp_call(
        session.ws_url,
        "Input.dispatchKeyEvent",
        {"type": "rawKeyDown", **params},
    )
    await _cdp_call(
        session.ws_url,
        "Input.dispatchKeyEvent",
        {"type": "keyUp", **params},
    )


async def _configure_viewport(session: _ManagedLiveSession) -> None:
    await _cdp_call(session.ws_url, "Page.enable")
    await _cdp_call(
        session.ws_url,
        "Emulation.setDeviceMetricsOverride",
        {
            "width": session.viewport_width,
            "height": session.viewport_height,
            "deviceScaleFactor": 1,
            "mobile": False,
        },
    )


async def _refresh_page_metadata(session: _ManagedLiveSession) -> None:
    try:
        result = await _cdp_call(
            session.ws_url,
            "Runtime.evaluate",
            {
                "expression": "({title: document.title, url: location.href})",
                "returnByValue": True,
            },
        )
    except HTTPException:
        return
    value = result.get("result", {}).get("value")
    if isinstance(value, dict):
        title = value.get("title")
        url = value.get("url")
        session.title = title if isinstance(title, str) else None
        session.current_url = url if isinstance(url, str) else None


async def _create_browser_target(target_url: str) -> dict[str, str]:
    host, port = _browser_endpoint()
    endpoint = f"http://{host}:{port}/json/new?{quote(target_url, safe='')}"
    try:
        async with httpx.AsyncClient(timeout=_CDP_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.put(endpoint)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Browser target creation failed: {exc}",
        ) from exc

    target_id = data.get("id")
    ws_url = data.get("webSocketDebuggerUrl")
    if not isinstance(target_id, str) or not isinstance(ws_url, str):
        raise HTTPException(status_code=502, detail="Browser returned an invalid target")
    return {"id": target_id, "webSocketDebuggerUrl": _normalize_ws_url(ws_url, host)}


async def _cdp_call(
    ws_url: str,
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_id = secrets.randbelow(1_000_000_000)
    payload: dict[str, Any] = {"id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    try:
        async with websockets.connect(ws_url, max_size=16 * 1024 * 1024) as websocket:
            await websocket.send(json.dumps(payload))
            while True:
                raw = await asyncio.wait_for(
                    websocket.recv(),
                    timeout=_CDP_WS_TIMEOUT_SECONDS,
                )
                message = json.loads(raw)
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    error = message["error"]
                    detail = error.get("message") if isinstance(error, dict) else str(error)
                    raise HTTPException(
                        status_code=502,
                        detail=f"Browser command failed: {detail}",
                    )
                result = message.get("result", {})
                return result if isinstance(result, dict) else {}
    except HTTPException:
        raise
    except (
        TimeoutError,
        OSError,
        json.JSONDecodeError,
        websockets.WebSocketException,
    ) as exc:
        raise HTTPException(status_code=503, detail=f"Browser command unavailable: {exc}") from exc


async def _require_session(session_id: str) -> _ManagedLiveSession:
    await _cleanup_expired_sessions()
    session = _LIVE_SESSIONS.get(session_id)
    if session is None or session.state != "active":
        raise HTTPException(status_code=404, detail="Live session not found")
    return session


async def _cleanup_expired_sessions() -> None:
    now = _now()
    expired = [session for session in _LIVE_SESSIONS.values() if session.expires_at <= now]
    for session in expired:
        await _close_session(session, state="expired")
        async with _LIVE_SESSION_LOCK:
            _LIVE_SESSIONS.pop(session.id, None)


async def _close_session(
    session: _ManagedLiveSession,
    *,
    state: LiveSessionState = "closed",
) -> None:
    session.state = state
    host, port = _browser_endpoint()
    close_url = f"http://{host}:{port}/json/close/{session.target_id}"
    try:
        async with httpx.AsyncClient(timeout=_CDP_HTTP_TIMEOUT_SECONDS) as client:
            await client.get(close_url)
    except httpx.HTTPError:
        return


def _status_from_session(session: _ManagedLiveSession) -> LiveSessionStatus:
    return LiveSessionStatus(
        id=session.id,
        kind=session.kind,
        state=session.state,
        target_url=session.target_url,
        current_url=session.current_url,
        title=session.title,
        sensitive=session.sensitive,
        created_at=session.created_at,
        expires_at=session.expires_at,
        viewport_width=session.viewport_width,
        viewport_height=session.viewport_height,
        control_enabled=session.control_enabled,
        control_owner="operator" if session.control_enabled else None,
        viewer_connected=session.viewer_connected,
        token_required=session.sensitive,
        last_viewed_at=session.last_viewed_at,
        last_controlled_at=session.last_controlled_at,
        audit_events=list(session.audit_events or []),
        control_policy=(
            "operator token required; input starts locked and must be enabled"
        ),
        capture_policy=(
            "sensitive frames require the operator token and are not persisted"
            if session.sensitive
            else "frames are transient and not persisted"
        ),
    )


def _require_view_authorization(
    session: _ManagedLiveSession,
    operator_token: str,
) -> LiveAuditActor:
    if _operator_token_valid(session, operator_token):
        return "operator"
    if session.sensitive:
        raise HTTPException(status_code=403, detail="Operator token required")
    return "internal"


def _require_operator_token(
    session: _ManagedLiveSession,
    operator_token: str,
) -> None:
    if not _operator_token_valid(session, operator_token):
        raise HTTPException(status_code=403, detail="Operator token required")


def _operator_token_valid(session: _ManagedLiveSession, operator_token: str) -> bool:
    if not operator_token:
        return False
    return secrets.compare_digest(
        session.operator_token_hash,
        _token_hash(operator_token),
    )


def _token_hash(operator_token: str) -> str:
    return hashlib.sha256(operator_token.encode("utf-8")).hexdigest()


def _audit(
    session: _ManagedLiveSession,
    *,
    actor: LiveAuditActor,
    action: str,
    detail: str | None = None,
) -> None:
    events = session.audit_events
    if events is None:
        events = []
        session.audit_events = events
    event = LiveSessionAuditEvent(
        at=_now(),
        actor=actor,
        action=action,
        detail=detail,
    )
    if action == "viewed" and events and events[-1].action == "viewed":
        events[-1] = event
    else:
        events.append(event)
    del events[:-30]


def _browser_endpoint() -> tuple[str, int]:
    host = (
        os.environ.get("SUMMITFLOW_LIVE_BROWSER_HOST", "").strip()
        or os.environ.get("SF_BROWSER_HOST", "").strip()
        or _DEFAULT_BROWSER_HOST
    )
    raw_port = os.environ.get("SUMMITFLOW_LIVE_BROWSER_PORT", "").strip()
    try:
        port = int(raw_port) if raw_port else _DEFAULT_BROWSER_PORT
    except ValueError:
        port = _DEFAULT_BROWSER_PORT
    return host, port


def _normalize_ws_url(ws_url: str, host: str) -> str:
    return ws_url.replace("ws://0.0.0.0:", f"ws://{host}:").replace(
        "ws://127.0.0.1:",
        f"ws://{host}:",
    )


def _validate_target_url(target_url: str) -> None:
    if target_url == "about:blank":
        return
    if target_url.startswith(("https://", "http://")):
        return
    raise HTTPException(
        status_code=400,
        detail="target_url must be http, https, or about:blank",
    )


def _now() -> datetime:
    return datetime.now(UTC)


_KEY_CODES: dict[str, int] = {
    "Backspace": 8,
    "Tab": 9,
    "Enter": 13,
    "Escape": 27,
    "ArrowLeft": 37,
    "ArrowUp": 38,
    "ArrowRight": 39,
    "ArrowDown": 40,
    "Delete": 46,
    "Home": 36,
    "End": 35,
    "PageUp": 33,
    "PageDown": 34,
}
