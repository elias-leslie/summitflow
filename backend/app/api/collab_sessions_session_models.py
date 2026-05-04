from __future__ import annotations

from pydantic import BaseModel, Field

from .collab_sessions_annotation_models import (
    CollabAnnotationResponse,
    CollabAuditEventResponse,
    CollabEvidencePacketResponse,
)
from .collab_sessions_participant_models import CollabParticipantResponse
from .collab_sessions_types import SessionState, TargetMode


class CollabSessionCreateRequest(BaseModel):
    project_id: str | None = None
    title: str = Field(default="Design Review Session", max_length=160)
    target_url: str | None = Field(default=None, max_length=2048)
    target_mode: TargetMode = "live_browser"
    agent_hub_session_id: str | None = Field(default=None, max_length=120)
    sensitive: bool = True


class CollabSessionResponse(BaseModel):
    session_id: str
    project_id: str | None
    title: str
    target_url: str | None
    target_mode: TargetMode
    agent_hub_session_id: str | None
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


class CollabControlGrantRequest(BaseModel):
    owner: str | None = Field(default="operator", max_length=80)
    ttl_seconds: int = Field(default=600, ge=1, le=3600)


class CollabSessionDetailResponse(CollabSessionResponse):
    participants: list[CollabParticipantResponse]
    annotations: list[CollabAnnotationResponse]
    evidence_packets: list[CollabEvidencePacketResponse]
    audit_events: list[CollabAuditEventResponse]
