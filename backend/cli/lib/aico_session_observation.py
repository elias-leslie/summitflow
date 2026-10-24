"""Optional local Aico owner observations for session monitor; never persisted.

Tether, the session daemon that owns Aico's sessions, answers them; without it
there is no observation.
"""

from __future__ import annotations

import http.client
import os
import re
from typing import Any, cast
from uuid import UUID

from app.services import tether

from ..commands.sessions_native_inspection import transcript_library

# Tether live-verifies the session before answering.
TETHER_TIMEOUT_SECONDS = 1.0
MAX_OWNER_RESPONSE_BYTES = 4096


def _query_tether(widget: str) -> object:
    """Tether's session descriptor in the legacy owner receipt shape, or None."""
    status, data = tether.request_first("GET", f"/v1/sessions/{widget}", timeout=TETHER_TIMEOUT_SECONDS,
                                        max_bytes=MAX_OWNER_RESPONSE_BYTES)
    if status != 200 or not isinstance(data, dict) or not isinstance(data.get("tmux"), dict):
        return None
    return {"owner": "aico", "widgetId": data.get("id"), "sessionId": data.get("ownershipId"),
            "generation": data.get("generation"), "tmuxSessionId": data["tmux"].get("sessionId"),
            "paneId": data["tmux"].get("paneId")}


def _eligible_identity(session: dict[str, Any]) -> dict[str, Any] | None:
    thread = session.get("id")
    if not isinstance(thread, str):
        return None
    try:
        if thread != str(UUID(thread)):
            return None
    except ValueError:
        return None
    metadata = session.get("provider_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    external = session.get("external_identity") or metadata.get("external_identity")
    if (session.get("host", metadata.get("host")) != os.uname().nodename
            or session.get("parent_session_id")
            or not isinstance(external, dict)
            or external.get("harness") != "codex"
            or external.get("launcher") != "aico"
            or external.get("runtime_session_id") != thread
            or external.get("agent_path") != "/root"):
        return None
    return external


def _observation(session: dict[str, Any], external: dict[str, Any], infos: list[Any]) -> dict[str, Any] | None:
    matches = [info for info in infos if info.session_id == session["id"]]
    if len(matches) != 1:
        return None
    info = matches[0]
    owner = info.process_owner
    if (not info.is_open or info.ownership_ambiguous or info.identity_error
            or info.parent_session_id or info.agent_path not in {None, "/root"}
            or owner is None or owner.harness != "codex"
            or owner.aico_widget_id != external.get("aico_widget_id")
            or owner.aico_session_id != external.get("aico_session_id")
            or re.fullmatch(r"[0-9a-f]{8}", owner.aico_widget_id) is None):
        return None
    wire = _query_tether(owner.aico_widget_id)
    if not isinstance(wire, dict):
        return None
    wire = cast(dict[str, Any], wire)
    if (wire.get("owner") != "aico"
            or wire.get("widgetId") != owner.aico_widget_id
            or wire.get("sessionId") != owner.aico_session_id
            or not isinstance(wire.get("generation"), str)
            or re.fullmatch(r"[0-9a-f]{64}", wire["generation"]) is None
            or not isinstance(wire.get("tmuxSessionId"), str)
            or re.fullmatch(r"\$\d+", wire["tmuxSessionId"]) is None
            or not isinstance(wire.get("paneId"), str)
            or re.fullmatch(r"%\d+", wire["paneId"]) is None):
        return None
    return {key: wire[key] for key in (
        "owner", "widgetId", "sessionId", "generation", "tmuxSessionId", "paneId",
    )}


def observe_aico_owners(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add only fresh, exactly correlated owner receipts; failure stays diagnostic."""
    projected = [{**session, "aico_owner_observation": None} for session in sessions]
    try:
        eligible = [(session, identity) for session in projected
                    if (identity := _eligible_identity(session)) is not None]
        if not eligible:
            return projected
        if not tether.present_sockets():
            return projected  # no owner at all: skip transcript discovery
        library = transcript_library()
        snapshot = library.discover_open_transcripts()
        threads = {session["id"] for session, _ in eligible}
        paths = [path for path in snapshot.paths
                 if any(path.name.endswith(f"{thread}.jsonl") for thread in threads)]
        infos = [info for path in paths
                 if (info := library.read_transcript_info(path, open_snapshot=snapshot)) is not None]
    except (OSError, ValueError, TypeError, ImportError):
        return projected
    for session, identity in eligible:
        try:
            observation = _observation(session, identity, infos)
        except (OSError, ValueError, TypeError, http.client.HTTPException):
            observation = None
        if observation is not None:
            session["tmux_pane_id"] = observation["paneId"]
            session["aico_owner_observation"] = observation
    return projected
