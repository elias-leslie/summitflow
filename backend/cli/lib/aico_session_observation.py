"""Optional local Aico owner observations for session monitor; never persisted."""

from __future__ import annotations

import http.client
import json
import os
import re
import socket
import stat
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from ..commands.sessions_native_inspection import transcript_library

OWNER_TIMEOUT_SECONDS = 0.25
MAX_OWNER_RESPONSE_BYTES = 4096


def _owner_socket() -> str:
    root = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    path = os.environ.get("AICO_CONTROL_SOCKET", str(Path(root) / "aico/control.sock"))
    if (not path.startswith("/") or "\0" in path or len(os.fsencode(path)) > 107
            or any(part in {"", ".", ".."} for part in path.split("/")[1:])):
        raise ValueError("invalid owner socket")
    info = os.lstat(path)
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("unavailable local owner socket")
    return path


class _OwnerConnection(http.client.HTTPConnection):
    def __init__(self, path: str) -> None:
        super().__init__("localhost", timeout=OWNER_TIMEOUT_SECONDS)
        self.path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(OWNER_TIMEOUT_SECONDS)
        self.sock.connect(self.path)


def _query_owner(path: str, widget: str) -> object:
    connection = _OwnerConnection(path)
    try:
        connection.request("GET", f"/v1/sessions/{widget}")
        response = connection.getresponse()
        if response.status != 200:
            return None
        body = response.read(MAX_OWNER_RESPONSE_BYTES + 1)
        if len(body) > MAX_OWNER_RESPONSE_BYTES:
            return None
        return json.loads(body)
    finally:
        connection.close()


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


def _observation(session: dict[str, Any], external: dict[str, Any], infos: list[Any], path: str) -> dict[str, Any] | None:
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
    wire = _query_owner(path, owner.aico_widget_id)
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
        path = _owner_socket()
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
            observation = _observation(session, identity, infos, path)
        except (OSError, ValueError, TypeError, http.client.HTTPException):
            observation = None
        if observation is not None:
            session["tmux_pane_id"] = observation["paneId"]
            session["aico_owner_observation"] = observation
    return projected
