from __future__ import annotations

import asyncio
import math
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, Field

from ..storage import collab_sessions as collab_store
from .dependencies import validate_project_exists

TargetMode = Literal["live_browser", "windows_co_browser", "st_browser", "manual"]
SessionState = Literal["active", "closed"]
AnnotationKind = Literal["pin", "box", "highlight", "pointer", "comment"]
ActorKind = Literal["user", "agent", "system"]
ParticipantRole = Literal["viewer", "controller", "observer"]
ParticipantStatus = Literal["active", "idle", "left"]

global_router = APIRouter()
project_router = APIRouter()

_DISPLAY_NAME_HEADERS = (
    "x-user-name",
    "x-user-display-name",
    "x-auth-request-user",
    "x-forwarded-user",
    "x-user-email",
    "x-auth-request-email",
    "remote-user",
)
_MAX_COMPACT_CONTEXT_CHARS = 600


class _CollabEventHub:
    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        self._sequences: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, session_id: str) -> int:
        await websocket.accept()
        async with self._lock:
            self._connections[session_id].append(websocket)
            return self._sequences[session_id]

    async def disconnect(self, websocket: WebSocket, session_id: str) -> None:
        async with self._lock:
            if websocket in self._connections[session_id]:
                self._connections[session_id].remove(websocket)
            if not self._connections[session_id]:
                self._connections.pop(session_id, None)

    async def current_sequence(self, session_id: str) -> int:
        async with self._lock:
            return self._sequences[session_id]

    async def broadcast(
        self,
        session_id: str,
        action: str,
        data: dict[str, Any],
    ) -> None:
        async with self._lock:
            self._sequences[session_id] += 1
            sequence = self._sequences[session_id]
            connections = list(self._connections.get(session_id, []))
        if not connections:
            return
        payload = {
            "type": "collab_event",
            "session_id": session_id,
            "sequence": sequence,
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "data": data,
        }
        disconnected: list[WebSocket] = []
        for websocket in connections:
            try:
                await websocket.send_json(payload)
            except Exception:
                disconnected.append(websocket)
        for websocket in disconnected:
            await self.disconnect(websocket, session_id)


_event_hub = _CollabEventHub()


class CollabSessionCreateRequest(BaseModel):
    project_id: str | None = None
    title: str = Field(default="Design Review Session", max_length=160)
    target_url: str | None = Field(default=None, max_length=2048)
    target_mode: TargetMode = "live_browser"
    sensitive: bool = True


class CollabSessionResponse(BaseModel):
    session_id: str
    project_id: str | None
    title: str
    target_url: str | None
    target_mode: TargetMode
    state: SessionState
    sensitive: bool
    control_owner: str | None
    control_expires_at: str | None
    browser_target_source: str | None
    media_strategy: str
    evidence_policy: str
    created_by_kind: str
    created_by_display: str | None
    created_at: str | None
    updated_at: str | None
    closed_at: str | None


class CollabAnnotationCreateRequest(BaseModel):
    kind: AnnotationKind = "pin"
    page_key: str | None = Field(default=None, max_length=512)
    page_url_snapshot: str | None = Field(default=None, max_length=2048)
    selector: str | None = Field(default=None, max_length=512)
    anchor: dict[str, Any]
    comment: str = Field(max_length=600)


class CollabParticipantCreateRequest(BaseModel):
    actor_kind: ActorKind = "user"
    display_name: str | None = Field(default=None, max_length=120)
    role: ParticipantRole = "viewer"


class CollabParticipantResponse(BaseModel):
    participant_id: str
    session_id: str
    participant_key: str
    actor_kind: ActorKind
    display_name: str | None
    role: ParticipantRole
    status: ParticipantStatus
    last_seen_at: str | None
    joined_at: str | None


class CollabAnnotationResponse(BaseModel):
    annotation_id: str
    session_id: str
    kind: AnnotationKind
    page_key: str | None
    page_url_snapshot: str | None
    selector: str | None
    anchor: dict[str, Any]
    comment: str
    created_by_kind: str
    created_by_display: str | None
    created_at: str | None


class CollabEvidencePacketCreateRequest(BaseModel):
    annotation_id: str | None = None
    title: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2048)
    page_url_snapshot: str | None = Field(default=None, max_length=2048)
    viewport: dict[str, Any] = Field(default_factory=dict)
    selector: str | None = Field(default=None, max_length=512)
    bbox: dict[str, Any] | None = None
    context_summary: str = Field(max_length=_MAX_COMPACT_CONTEXT_CHARS)
    artifact_id: str | None = Field(default=None, max_length=120)


class CollabEvidencePacketResponse(BaseModel):
    evidence_id: str
    session_id: str
    annotation_id: str | None
    title: str | None
    url: str | None
    page_url_snapshot: str | None
    viewport: dict[str, Any]
    selector: str | None
    bbox: dict[str, Any] | None
    context_summary: str
    artifact_id: str | None
    token_estimate: int
    created_by_kind: str
    created_by_display: str | None
    created_at: str | None


class CollabControlGrantRequest(BaseModel):
    owner: str | None = Field(default="operator", max_length=80)
    ttl_seconds: int = Field(default=600, ge=1, le=3600)


class CollabAuditEventResponse(BaseModel):
    audit_id: str
    session_id: str
    actor_kind: str
    action: str
    detail: dict[str, Any]
    created_at: str | None


class CollabSessionDetailResponse(CollabSessionResponse):
    participants: list[CollabParticipantResponse]
    annotations: list[CollabAnnotationResponse]
    evidence_packets: list[CollabEvidencePacketResponse]
    audit_events: list[CollabAuditEventResponse]


def _derive_created_by_display(request: Request) -> str | None:
    for header_name in _DISPLAY_NAME_HEADERS:
        value = request.headers.get(header_name)
        if value and value.strip():
            return value.strip()
    return None


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)


def _normalize_title(title: str) -> str:
    normalized = title.strip()
    if not normalized:
        raise _bad_request("title is required")
    return normalized


def _normalize_comment(comment: str) -> str:
    normalized = comment.strip()
    if not normalized:
        raise _bad_request("comment is required")
    return normalized


def _normalize_optional_text(value: str | None) -> str | None:
    normalized = value.strip() if isinstance(value, str) else None
    return normalized or None


def _validate_url(value: str | None) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    if normalized == "about:blank" or normalized.startswith(("https://", "http://")):
        return normalized
    raise _bad_request("target_url must be http, https, or about:blank")


def _validate_finite_number(value: Any, *, field_name: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise _bad_request(f"Invalid anchor field: {field_name}")
    return float(value)


def _normalize_anchor(anchor: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(anchor, dict):
        raise _bad_request("anchor is required")
    normalized = {
        "coordinate_space": "viewport_css_px",
        "x": _validate_finite_number(anchor.get("x"), field_name="x"),
        "y": _validate_finite_number(anchor.get("y"), field_name="y"),
        "viewport_width": _validate_finite_number(
            anchor.get("viewport_width"),
            field_name="viewport_width",
        ),
        "viewport_height": _validate_finite_number(
            anchor.get("viewport_height"),
            field_name="viewport_height",
        ),
    }
    for field_name in ("scroll_x", "scroll_y", "width", "height"):
        if field_name in anchor and anchor[field_name] is not None:
            normalized[field_name] = _validate_finite_number(
                anchor[field_name],
                field_name=field_name,
            )
    viewport_width = float(normalized["viewport_width"])
    viewport_height = float(normalized["viewport_height"])
    width = float(normalized.get("width", 0))
    height = float(normalized.get("height", 0))
    if viewport_width < 0 or viewport_height < 0:
        raise _bad_request("Invalid anchor field: viewport dimensions must be non-negative")
    if width < 0 or height < 0:
        raise _bad_request("Invalid anchor field: dimensions must be non-negative")
    return normalized


def _require_session(session_id: str) -> dict[str, Any]:
    session = collab_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Collab session not found")
    return session


def _require_active_session(session_id: str) -> dict[str, Any]:
    session = _require_session(session_id)
    if session["state"] != "active":
        raise HTTPException(status_code=409, detail="Collab session is closed")
    return session


async def _broadcast_collab_event(
    session_id: str,
    action: str,
    data: dict[str, Any],
) -> None:
    await _event_hub.broadcast(session_id, action, data)


@global_router.get("/collab/sessions", response_model=list[CollabSessionResponse])
async def list_collab_sessions(
    project_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=250),
) -> list[CollabSessionResponse]:
    if project_id:
        validate_project_exists(project_id)
    rows = collab_store.list_sessions(project_id=project_id, limit=limit)
    return [CollabSessionResponse(**row) for row in rows]


@global_router.post("/collab/sessions", response_model=CollabSessionResponse, status_code=201)
async def create_collab_session(
    payload: CollabSessionCreateRequest,
    request: Request,
) -> CollabSessionResponse:
    if payload.project_id:
        validate_project_exists(payload.project_id)
    row = collab_store.create_session(
        project_id=payload.project_id,
        title=_normalize_title(payload.title),
        target_url=_validate_url(payload.target_url),
        target_mode=payload.target_mode,
        sensitive=payload.sensitive,
        created_by_display=_derive_created_by_display(request),
    )
    await _broadcast_collab_event(
        row["session_id"],
        "session-created",
        {"target_mode": row["target_mode"], "sensitive": row["sensitive"]},
    )
    return CollabSessionResponse(**row)


@global_router.get("/collab/sessions/{session_id}", response_model=CollabSessionDetailResponse)
async def get_collab_session(session_id: str) -> CollabSessionDetailResponse:
    row = collab_store.get_session_detail(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Collab session not found")
    return CollabSessionDetailResponse(**row)


@global_router.websocket("/collab/sessions/{session_id}/events")
async def collab_session_events(websocket: WebSocket, session_id: str) -> None:
    session = collab_store.get_session(session_id)
    if not session:
        await websocket.accept()
        await websocket.send_json(
            {
                "type": "error",
                "session_id": session_id,
                "data": {"error": f"Collab session not found: {session_id}"},
            }
        )
        await websocket.close(code=1008, reason="Collab session not found")
        return

    sequence = await _event_hub.connect(websocket, session_id)
    try:
        await websocket.send_json(
            {
                "type": "connected",
                "session_id": session_id,
                "sequence": sequence,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        while True:
            data = await websocket.receive_json()
            if isinstance(data, dict) and data.get("type") == "ping":
                await websocket.send_json(
                    {
                        "type": "pong",
                        "session_id": session_id,
                        "sequence": await _event_hub.current_sequence(session_id),
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )
    except WebSocketDisconnect:
        pass
    finally:
        await _event_hub.disconnect(websocket, session_id)


@global_router.post(
    "/collab/sessions/{session_id}/participants",
    response_model=CollabParticipantResponse,
    status_code=201,
)
async def join_collab_session(
    session_id: str,
    payload: CollabParticipantCreateRequest,
    request: Request,
) -> CollabParticipantResponse:
    _require_active_session(session_id)
    display_name = _normalize_optional_text(payload.display_name)
    if display_name is None:
        display_name = _derive_created_by_display(request)
    row = collab_store.upsert_participant(
        session_id=session_id,
        actor_kind=payload.actor_kind,
        display_name=display_name,
        role=payload.role,
    )
    await _broadcast_collab_event(
        session_id,
        "participant-seen",
        {
            "participant_id": row["participant_id"],
            "actor_kind": row["actor_kind"],
            "role": row["role"],
        },
    )
    return CollabParticipantResponse(**row)


@global_router.post(
    "/collab/sessions/{session_id}/annotations",
    response_model=CollabAnnotationResponse,
    status_code=201,
)
async def create_collab_annotation(
    session_id: str,
    payload: CollabAnnotationCreateRequest,
    request: Request,
) -> CollabAnnotationResponse:
    _require_active_session(session_id)
    row = collab_store.create_annotation(
        session_id=session_id,
        kind=payload.kind,
        page_key=_normalize_optional_text(payload.page_key),
        page_url_snapshot=_validate_url(payload.page_url_snapshot),
        selector=_normalize_optional_text(payload.selector),
        anchor=_normalize_anchor(payload.anchor),
        comment=_normalize_comment(payload.comment),
        created_by_display=_derive_created_by_display(request),
    )
    await _broadcast_collab_event(
        session_id,
        "annotation-created",
        {"annotation_id": row["annotation_id"], "kind": row["kind"]},
    )
    return CollabAnnotationResponse(**row)


@global_router.post(
    "/collab/sessions/{session_id}/evidence-packets",
    response_model=CollabEvidencePacketResponse,
    status_code=201,
)
async def create_collab_evidence_packet(
    session_id: str,
    payload: CollabEvidencePacketCreateRequest,
    request: Request,
) -> CollabEvidencePacketResponse:
    session = _require_active_session(session_id)
    if session["sensitive"]:
        raise HTTPException(
            status_code=423,
            detail="Evidence packet creation is blocked while sensitive mode is active",
        )
    context_summary = payload.context_summary.strip()
    if not context_summary:
        raise _bad_request("context_summary is required")
    row = collab_store.create_evidence_packet(
        session_id=session_id,
        annotation_id=_normalize_optional_text(payload.annotation_id),
        title=_normalize_optional_text(payload.title),
        url=_validate_url(payload.url),
        page_url_snapshot=_validate_url(payload.page_url_snapshot),
        viewport=payload.viewport,
        selector=_normalize_optional_text(payload.selector),
        bbox=payload.bbox,
        context_summary=context_summary,
        artifact_id=_normalize_optional_text(payload.artifact_id),
        created_by_display=_derive_created_by_display(request),
    )
    await _broadcast_collab_event(
        session_id,
        "evidence-created",
        {"evidence_id": row["evidence_id"], "token_estimate": row["token_estimate"]},
    )
    return CollabEvidencePacketResponse(**row)


@global_router.post("/collab/sessions/{session_id}/control-grant", response_model=CollabSessionResponse)
async def set_collab_control_grant(
    session_id: str,
    payload: CollabControlGrantRequest,
) -> CollabSessionResponse:
    _require_active_session(session_id)
    owner = _normalize_optional_text(payload.owner)
    row = collab_store.set_control_grant(
        session_id=session_id,
        owner=owner,
        ttl_seconds=payload.ttl_seconds,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Collab session not found")
    await _broadcast_collab_event(
        session_id,
        "control-updated",
        {"control_owner": row["control_owner"], "expires_at": row["control_expires_at"]},
    )
    return CollabSessionResponse(**row)


@global_router.post("/collab/sessions/{session_id}/teardown", response_model=CollabSessionResponse)
async def teardown_collab_session(session_id: str) -> CollabSessionResponse:
    row = collab_store.teardown_session(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Collab session not found")
    await _broadcast_collab_event(session_id, "teardown", {"state": row["state"]})
    return CollabSessionResponse(**row)


@project_router.get(
    "/{project_id}/collab/sessions",
    response_model=list[CollabSessionResponse],
)
async def list_project_collab_sessions(
    project_id: str,
    limit: int = Query(100, ge=1, le=250),
) -> list[CollabSessionResponse]:
    validate_project_exists(project_id)
    rows = collab_store.list_sessions(project_id=project_id, limit=limit)
    return [CollabSessionResponse(**row) for row in rows]


@project_router.post(
    "/{project_id}/collab/sessions",
    response_model=CollabSessionResponse,
    status_code=201,
)
async def create_project_collab_session(
    project_id: str,
    payload: CollabSessionCreateRequest,
    request: Request,
) -> CollabSessionResponse:
    validate_project_exists(project_id)
    row = collab_store.create_session(
        project_id=project_id,
        title=_normalize_title(payload.title),
        target_url=_validate_url(payload.target_url),
        target_mode=payload.target_mode,
        sensitive=payload.sensitive,
        created_by_display=_derive_created_by_display(request),
    )
    await _broadcast_collab_event(
        row["session_id"],
        "session-created",
        {"target_mode": row["target_mode"], "sensitive": row["sensitive"]},
    )
    return CollabSessionResponse(**row)
