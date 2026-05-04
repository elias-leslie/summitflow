from __future__ import annotations

from pydantic import BaseModel

from .collab_sessions_connector_models import CollabConnectorPairingResponse
from .collab_sessions_session_models import CollabSessionResponse


class CollabConnectorPairingClaimResponse(BaseModel):
    pairing: CollabConnectorPairingResponse
    connector_token: str
    session: CollabSessionResponse
