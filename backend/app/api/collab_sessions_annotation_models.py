from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .collab_sessions_types import MAX_COMPACT_CONTEXT_CHARS, ActorKind, AnnotationKind


class CollabAnnotationCreateRequest(BaseModel):
    kind: AnnotationKind = "pin"
    page_key: str | None = Field(default=None, max_length=512)
    page_url_snapshot: str | None = Field(default=None, max_length=2048)
    selector: str | None = Field(default=None, max_length=512)
    anchor: dict[str, Any]
    comment: str = Field(max_length=600)
    created_by_kind: ActorKind = "user"


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
    context_summary: str = Field(max_length=MAX_COMPACT_CONTEXT_CHARS)
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


class CollabAuditEventResponse(BaseModel):
    audit_id: str
    session_id: str
    actor_kind: str
    action: str
    detail: dict[str, Any]
    created_at: str | None
