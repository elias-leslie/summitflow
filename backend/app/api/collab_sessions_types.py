from __future__ import annotations

from typing import Literal

TargetMode = Literal["live_browser", "windows_co_browser", "st_browser", "manual"]
SessionState = Literal["active", "closed"]
AnnotationKind = Literal["pin", "box", "highlight", "pointer", "comment"]
ActorKind = Literal["user", "agent", "system"]
ParticipantRole = Literal["viewer", "controller", "observer"]
ParticipantStatus = Literal["active", "idle", "left"]
ConnectorPairingState = Literal["pending", "claimed", "revoked", "expired"]

MAX_COMPACT_CONTEXT_CHARS = 600
