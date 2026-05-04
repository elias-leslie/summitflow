from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .collab_sessions_types import ConnectorPairingState


class CollabConnectorPairingCreateRequest(BaseModel):
    expires_in_seconds: int = Field(default=600, ge=60, le=3600)
    connector_host: str | None = Field(default=None, max_length=120)
    profile_label: str | None = Field(default=None, max_length=120)


class CollabConnectorPairingResponse(BaseModel):
    pairing_id: str
    session_id: str
    state: ConnectorPairingState
    connector_host: str | None
    profile_label: str | None
    connector_version: str | None
    connector_state: dict[str, Any]
    expires_at: str | None
    claimed_at: str | None
    connector_last_seen_at: str | None
    revoked_at: str | None
    created_at: str | None
    updated_at: str | None


class CollabConnectorPairingCreateResponse(CollabConnectorPairingResponse):
    pairing_token: str


class CollabConnectorPairingClaimRequest(BaseModel):
    pairing_token: str = Field(min_length=16, max_length=200)
    connector_host: str | None = Field(default=None, max_length=120)
    profile_label: str | None = Field(default=None, max_length=120)
    connector_version: str | None = Field(default=None, max_length=80)


class CollabConnectorHeartbeatRequest(BaseModel):
    connector_token: str = Field(min_length=16, max_length=200)
    url: str | None = Field(default=None, max_length=2048)
    title: str | None = Field(default=None, max_length=200)
    scroll_x: float | None = None
    scroll_y: float | None = None
    viewport_width: float | None = None
    viewport_height: float | None = None
    dom_state_hash: str | None = Field(default=None, max_length=128)
