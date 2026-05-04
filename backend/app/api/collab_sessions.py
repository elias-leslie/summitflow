from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)

from ..services.collab_connector_tokens import generate_connector_token, hash_connector_token
from ..storage import collab_sessions as collab_store
from ..utils.shared_paths import get_repo_root
from .collab_sessions_annotation_models import (
    CollabAnnotationCreateRequest,
    CollabAnnotationResponse,
    CollabEvidencePacketCreateRequest,
    CollabEvidencePacketResponse,
)
from .collab_sessions_connector_claim_models import CollabConnectorPairingClaimResponse
from .collab_sessions_connector_models import (
    CollabConnectorHeartbeatRequest,
    CollabConnectorPairingClaimRequest,
    CollabConnectorPairingCreateRequest,
    CollabConnectorPairingCreateResponse,
    CollabConnectorPairingResponse,
)
from .collab_sessions_events import CollabEventHub
from .collab_sessions_helpers import (
    bad_request as _bad_request,
)
from .collab_sessions_helpers import (
    derive_created_by_display as _derive_created_by_display,
)
from .collab_sessions_helpers import (
    normalize_anchor as _normalize_anchor,
)
from .collab_sessions_helpers import (
    normalize_comment as _normalize_comment,
)
from .collab_sessions_helpers import (
    normalize_connector_state as _normalize_connector_state,
)
from .collab_sessions_helpers import (
    normalize_optional_text as _normalize_optional_text,
)
from .collab_sessions_helpers import (
    normalize_title as _normalize_title,
)
from .collab_sessions_helpers import (
    normalize_token as _normalize_token,
)
from .collab_sessions_helpers import (
    raise_connector_pairing_error as _raise_connector_pairing_error,
)
from .collab_sessions_helpers import (
    require_active_session as _require_active_session,
)
from .collab_sessions_helpers import (
    require_session as _require_session,
)
from .collab_sessions_helpers import (
    validate_url as _validate_url,
)
from .collab_sessions_participant_models import (
    CollabParticipantCreateRequest,
    CollabParticipantResponse,
)
from .collab_sessions_session_models import (
    CollabControlGrantRequest,
    CollabSessionCreateRequest,
    CollabSessionDetailResponse,
    CollabSessionResponse,
)
from .dependencies import validate_project_exists

global_router = APIRouter()
project_router = APIRouter()

_EXTENSION_PACKAGE_FILES = (
    "manifest.json",
    "dist/background.js",
    "dist/content.js",
    "dist/pairingBridge.js",
)


_event_hub = CollabEventHub()


@global_router.get("/collab/chromium-extension.zip")
def download_chromium_extension() -> Response:
    """Return the built unpacked Chromium extension as a ZIP."""
    extension_root = get_repo_root() / "apps" / "summitflow-chromium-extension"
    missing = [
        relative_path
        for relative_path in _EXTENSION_PACKAGE_FILES
        if not (extension_root / relative_path).is_file()
    ]
    if missing:
        raise HTTPException(
            status_code=409,
            detail=(
                "Chromium extension package is not built. "
                "Build @summitflow/chromium-extension before downloading."
            ),
        )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative_path in _EXTENSION_PACKAGE_FILES:
            archive.write(extension_root / relative_path, arcname=relative_path)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "content-disposition": (
                'attachment; filename="summitflow-cobrowser-extension.zip"'
            )
        },
    )


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
        agent_hub_session_id=_normalize_optional_text(payload.agent_hub_session_id),
        sensitive=payload.sensitive,
        created_by_display=_derive_created_by_display(request),
    )
    await _broadcast_collab_event(
        row["session_id"],
        "session-created",
        {
            "target_mode": row["target_mode"],
            "sensitive": row["sensitive"],
            "agent_hub_session_id": row["agent_hub_session_id"],
        },
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


@global_router.get(
    "/collab/sessions/{session_id}/connector-pairings",
    response_model=list[CollabConnectorPairingResponse],
)
async def list_collab_connector_pairings(
    session_id: str,
    limit: int = Query(50, ge=1, le=100),
) -> list[CollabConnectorPairingResponse]:
    _require_session(session_id)
    rows = collab_store.list_connector_pairings(session_id=session_id, limit=limit)
    return [CollabConnectorPairingResponse(**row) for row in rows]


@global_router.post(
    "/collab/sessions/{session_id}/connector-pairings",
    response_model=CollabConnectorPairingCreateResponse,
    status_code=201,
)
async def create_collab_connector_pairing(
    session_id: str,
    payload: CollabConnectorPairingCreateRequest,
) -> CollabConnectorPairingCreateResponse:
    _require_active_session(session_id)
    pairing_token = generate_connector_token()
    expires_at = datetime.now(UTC) + timedelta(seconds=payload.expires_in_seconds)
    row = collab_store.create_connector_pairing(
        session_id=session_id,
        pairing_token_hash=hash_connector_token(pairing_token),
        expires_at=expires_at,
        connector_host=_normalize_optional_text(payload.connector_host),
        profile_label=_normalize_optional_text(payload.profile_label),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Collab session not found")
    await _broadcast_collab_event(
        session_id,
        "connector-pairing-created",
        {"pairing_id": row["pairing_id"], "expires_at": row["expires_at"]},
    )
    return CollabConnectorPairingCreateResponse(**row, pairing_token=pairing_token)


@global_router.post(
    "/collab/connector-pairings/{pairing_id}/claim",
    response_model=CollabConnectorPairingClaimResponse,
)
async def claim_collab_connector_pairing(
    pairing_id: str,
    payload: CollabConnectorPairingClaimRequest,
) -> CollabConnectorPairingClaimResponse:
    connector_token = generate_connector_token()
    row, error = collab_store.claim_connector_pairing(
        pairing_id=pairing_id,
        pairing_token_hash=hash_connector_token(_normalize_token(payload.pairing_token)),
        connector_token_hash=hash_connector_token(connector_token),
        connector_host=_normalize_optional_text(payload.connector_host),
        profile_label=_normalize_optional_text(payload.profile_label),
        connector_version=_normalize_optional_text(payload.connector_version),
    )
    _raise_connector_pairing_error(error)
    if not row:
        raise HTTPException(status_code=404, detail="Connector pairing not found")
    session = collab_store.get_session(row["session_id"])
    if not session:
        raise HTTPException(status_code=404, detail="Collab session not found")
    await _broadcast_collab_event(
        row["session_id"],
        "connector-paired",
        {
            "pairing_id": row["pairing_id"],
            "connector_host": row["connector_host"],
            "profile_label": row["profile_label"],
        },
    )
    return CollabConnectorPairingClaimResponse(
        pairing=CollabConnectorPairingResponse(**row),
        connector_token=connector_token,
        session=CollabSessionResponse(**session),
    )


@global_router.post(
    "/collab/connector-pairings/{pairing_id}/heartbeat",
    response_model=CollabConnectorPairingResponse,
)
async def heartbeat_collab_connector_pairing(
    pairing_id: str,
    payload: CollabConnectorHeartbeatRequest,
) -> CollabConnectorPairingResponse:
    row, error = collab_store.heartbeat_connector_pairing(
        pairing_id=pairing_id,
        connector_token_hash=hash_connector_token(_normalize_token(payload.connector_token)),
        connector_state=_normalize_connector_state(payload),
    )
    _raise_connector_pairing_error(error)
    if not row:
        raise HTTPException(status_code=404, detail="Connector pairing not found")
    await _broadcast_collab_event(
        row["session_id"],
        "connector-state-updated",
        {"pairing_id": row["pairing_id"], "connector_state": row["connector_state"]},
    )
    return CollabConnectorPairingResponse(**row)


@global_router.post(
    "/collab/connector-pairings/{pairing_id}/revoke",
    response_model=CollabConnectorPairingResponse,
)
async def revoke_collab_connector_pairing(pairing_id: str) -> CollabConnectorPairingResponse:
    row = collab_store.revoke_connector_pairing(pairing_id=pairing_id)
    if not row:
        raise HTTPException(status_code=404, detail="Connector pairing not found")
    await _broadcast_collab_event(
        row["session_id"],
        "connector-revoked",
        {"pairing_id": row["pairing_id"], "state": row["state"]},
    )
    return CollabConnectorPairingResponse(**row)


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
        created_by_kind=payload.created_by_kind,
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
        agent_hub_session_id=_normalize_optional_text(payload.agent_hub_session_id),
        sensitive=payload.sensitive,
        created_by_display=_derive_created_by_display(request),
    )
    await _broadcast_collab_event(
        row["session_id"],
        "session-created",
        {
            "target_mode": row["target_mode"],
            "sensitive": row["sensitive"],
            "agent_hub_session_id": row["agent_hub_session_id"],
        },
    )
    return CollabSessionResponse(**row)
