from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from ..storage import route_evidence as route_evidence_store
from .dependencies import validate_project_exists

router = APIRouter()


class RouteEvidenceCreateRequest(BaseModel):
    page_key: str | None = None
    page_url_snapshot: str | None = None
    comment: str | None = None
    selector: str | None = None
    anchor: dict[str, Any] | None = None


class RouteEvidenceResponse(BaseModel):
    evidence_id: str
    project_id: str
    page_key: str
    page_url_snapshot: str | None
    comment: str
    selector: str | None
    anchor: dict[str, Any]
    created_by_kind: str
    created_by_display: str | None
    created_at: str | None


_REQUIRED_ANCHOR_FIELDS = (
    "x",
    "y",
    "scroll_x",
    "scroll_y",
    "viewport_width",
    "viewport_height",
)
_OPTIONAL_BBOX_FIELDS = ("left", "top", "width", "height")
_DISPLAY_NAME_HEADERS = (
    "x-user-name",
    "x-user-display-name",
    "x-auth-request-user",
    "x-forwarded-user",
    "x-user-email",
    "x-auth-request-email",
    "remote-user",
)



def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)



def _validate_finite_number(value: Any, *, field_name: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise _bad_request(f"Invalid anchor field: {field_name}")
    return float(value)



def _normalize_anchor(anchor: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(anchor, dict):
        raise _bad_request("Anchor is required")

    normalized: dict[str, Any] = {
        "coordinate_space": "document_css_px",
    }

    for field in _REQUIRED_ANCHOR_FIELDS:
        normalized[field] = _validate_finite_number(anchor.get(field), field_name=field)

    viewport_width = float(normalized["viewport_width"])
    viewport_height = float(normalized["viewport_height"])
    if viewport_width < 0 or viewport_height < 0:
        raise _bad_request("Invalid anchor field: viewport dimensions must be non-negative")

    bbox = anchor.get("bbox")
    if bbox is not None:
        if not isinstance(bbox, dict):
            raise _bad_request("Invalid anchor field: bbox")
        normalized_bbox: dict[str, float] = {}
        for field in _OPTIONAL_BBOX_FIELDS:
            if field in bbox and bbox[field] is not None:
                normalized_bbox[field] = _validate_finite_number(
                    bbox[field],
                    field_name=f"bbox.{field}",
                )
        if "width" in normalized_bbox and normalized_bbox["width"] < 0:
            raise _bad_request("Invalid anchor field: bbox.width")
        if "height" in normalized_bbox and normalized_bbox["height"] < 0:
            raise _bad_request("Invalid anchor field: bbox.height")
        if normalized_bbox:
            normalized["bbox"] = normalized_bbox

    return normalized



def _normalize_page_key(page_key: str | None) -> str:
    normalized = route_evidence_store.normalize_page_key(page_key)
    if not normalized:
        raise _bad_request("page_key is required")
    return normalized



def _normalize_comment(comment: str | None) -> str:
    normalized = str(comment or "").strip()
    if not normalized:
        raise _bad_request("comment is required")
    return normalized



def _normalize_selector(selector: str | None) -> str | None:
    normalized = str(selector).strip() if isinstance(selector, str) else None
    return normalized or None



def _derive_created_by_display(request: Request) -> str | None:
    for header_name in _DISPLAY_NAME_HEADERS:
        value = request.headers.get(header_name)
        if value and value.strip():
            return value.strip()
    return None


@router.post("/{project_id}/route-evidence", response_model=RouteEvidenceResponse, status_code=201)
async def create_route_evidence(
    project_id: str,
    payload: RouteEvidenceCreateRequest,
    request: Request,
) -> RouteEvidenceResponse:
    validate_project_exists(project_id)

    record = route_evidence_store.create_route_evidence(
        project_id=project_id,
        page_key=_normalize_page_key(payload.page_key),
        page_url_snapshot=payload.page_url_snapshot,
        comment=_normalize_comment(payload.comment),
        selector=_normalize_selector(payload.selector),
        anchor=_normalize_anchor(payload.anchor),
        created_by_display=_derive_created_by_display(request),
    )
    return RouteEvidenceResponse(**record)


@router.get("/{project_id}/route-evidence", response_model=list[RouteEvidenceResponse])
async def list_route_evidence(
    project_id: str,
    page_key: str = Query(..., description="Normalized page key"),
    limit: int = Query(10, ge=1, le=100, description="Maximum evidence items to return"),
) -> list[RouteEvidenceResponse]:
    validate_project_exists(project_id)

    normalized_page_key = _normalize_page_key(page_key)
    rows = route_evidence_store.list_route_evidence(
        project_id=project_id,
        page_key=normalized_page_key,
        limit=limit,
    )
    return [RouteEvidenceResponse(**row) for row in rows]
