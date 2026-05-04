from __future__ import annotations

from pydantic import BaseModel, Field

from .collab_sessions_types import ActorKind, ParticipantRole, ParticipantStatus


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
