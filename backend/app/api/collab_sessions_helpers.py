from __future__ import annotations

import math
from typing import Any

from fastapi import HTTPException, Request

from ..storage import collab_sessions as collab_store
from .collab_sessions_connector_models import CollabConnectorHeartbeatRequest

_DISPLAY_NAME_HEADERS = (
    "x-user-name",
    "x-user-display-name",
    "x-auth-request-user",
    "x-forwarded-user",
    "x-user-email",
    "x-auth-request-email",
    "remote-user",
)


def derive_created_by_display(request: Request) -> str | None:
    for header_name in _DISPLAY_NAME_HEADERS:
        value = request.headers.get(header_name)
        if value and value.strip():
            return value.strip()
    return None


def bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)


def normalize_title(title: str) -> str:
    normalized = title.strip()
    if not normalized:
        raise bad_request("title is required")
    return normalized


def normalize_comment(comment: str) -> str:
    normalized = comment.strip()
    if not normalized:
        raise bad_request("comment is required")
    return normalized


def normalize_optional_text(value: str | None) -> str | None:
    normalized = value.strip() if isinstance(value, str) else None
    return normalized or None


def normalize_token(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise bad_request("token is required")
    return normalized


def validate_url(value: str | None) -> str | None:
    normalized = normalize_optional_text(value)
    if normalized is None:
        return None
    if normalized == "about:blank" or normalized.startswith(("https://", "http://")):
        return normalized
    raise bad_request("target_url must be http, https, or about:blank")


def validate_finite_number(value: Any, *, field_name: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise bad_request(f"Invalid anchor field: {field_name}")
    return float(value)


def normalize_anchor(anchor: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(anchor, dict):
        raise bad_request("anchor is required")
    normalized = {
        "coordinate_space": "viewport_css_px",
        "x": validate_finite_number(anchor.get("x"), field_name="x"),
        "y": validate_finite_number(anchor.get("y"), field_name="y"),
        "viewport_width": validate_finite_number(
            anchor.get("viewport_width"),
            field_name="viewport_width",
        ),
        "viewport_height": validate_finite_number(
            anchor.get("viewport_height"),
            field_name="viewport_height",
        ),
    }
    for field_name in ("scroll_x", "scroll_y", "width", "height"):
        if field_name in anchor and anchor[field_name] is not None:
            normalized[field_name] = validate_finite_number(
                anchor[field_name],
                field_name=field_name,
            )
    viewport_width = float(normalized["viewport_width"])
    viewport_height = float(normalized["viewport_height"])
    width = float(normalized.get("width", 0))
    height = float(normalized.get("height", 0))
    if viewport_width < 0 or viewport_height < 0:
        raise bad_request("Invalid anchor field: viewport dimensions must be non-negative")
    if width < 0 or height < 0:
        raise bad_request("Invalid anchor field: dimensions must be non-negative")
    return normalized


def normalize_connector_state(payload: CollabConnectorHeartbeatRequest) -> dict[str, Any]:
    state: dict[str, Any] = {}
    url = validate_url(payload.url)
    if url is not None:
        state["url"] = url
    title = normalize_optional_text(payload.title)
    if title is not None:
        state["title"] = title
    viewport: dict[str, float] = {}
    if payload.viewport_width is not None:
        viewport["width"] = validate_finite_number(
            payload.viewport_width,
            field_name="viewport_width",
        )
    if payload.viewport_height is not None:
        viewport["height"] = validate_finite_number(
            payload.viewport_height,
            field_name="viewport_height",
        )
    if viewport:
        state["viewport"] = viewport
    scroll: dict[str, float] = {}
    if payload.scroll_x is not None:
        scroll["x"] = validate_finite_number(payload.scroll_x, field_name="scroll_x")
    if payload.scroll_y is not None:
        scroll["y"] = validate_finite_number(payload.scroll_y, field_name="scroll_y")
    if scroll:
        state["scroll"] = scroll
    dom_state_hash = normalize_optional_text(payload.dom_state_hash)
    if dom_state_hash is not None:
        state["dom_state_hash"] = dom_state_hash
    return state


def require_session(session_id: str) -> dict[str, Any]:
    session = collab_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Collab session not found")
    return session


def require_active_session(session_id: str) -> dict[str, Any]:
    session = require_session(session_id)
    if session["state"] != "active":
        raise HTTPException(status_code=409, detail="Collab session is closed")
    return session


def raise_connector_pairing_error(error: str | None) -> None:
    if error is None:
        return
    if error == "not_found":
        raise HTTPException(status_code=404, detail="Connector pairing not found")
    if error == "invalid_token":
        raise HTTPException(status_code=403, detail="Connector token rejected")
    if error == "session_closed":
        raise HTTPException(status_code=409, detail="Collab session is closed")
    if error == "expired":
        raise HTTPException(status_code=409, detail="Connector pairing expired")
    if error == "revoked":
        raise HTTPException(status_code=409, detail="Connector pairing revoked")
    if error == "claimed":
        raise HTTPException(status_code=409, detail="Connector pairing already claimed")
    if error == "pending":
        raise HTTPException(status_code=409, detail="Connector pairing is not claimed")
    raise HTTPException(status_code=409, detail=f"Connector pairing unavailable: {error}")
