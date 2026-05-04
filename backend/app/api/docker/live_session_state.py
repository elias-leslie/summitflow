"""State, status, and authorization helpers for live sessions."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import UTC, datetime

import httpx
from fastapi import HTTPException

from .live_session_browser import _browser_endpoint, _browser_target_status
from .live_session_models import (
    _CDP_HTTP_TIMEOUT_SECONDS,
    LiveAuditActor,
    LiveSessionAuditEvent,
    LiveSessionState,
    LiveSessionStatus,
    _ManagedLiveSession,
)

_LIVE_SESSIONS: dict[str, _ManagedLiveSession] = {}
_LIVE_SESSION_LOCK = asyncio.Lock()


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
    _expire_control_grant(session)
    target = _browser_target_status()
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
        control_expires_at=session.control_expires_at,
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
        browser_target_host=target.host,
        browser_target_port=target.port,
        browser_target_source=target.source,
        browser_target_debug_local=target.debug_local,
    )


def _expire_control_grant(session: _ManagedLiveSession) -> None:
    if not session.control_enabled or session.control_expires_at is None:
        return
    if session.control_expires_at > _now():
        return
    session.control_enabled = False
    session.control_expires_at = None
    _audit(session, actor="internal", action="control-expired")


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


def _now() -> datetime:
    return datetime.now(UTC)
