#!/usr/bin/env python3
"""Sync external tmux agent sessions from A-Term into Agent Hub.

Agent sessions follow the `{mode}-{project}` naming convention. They are found
on the host's default tmux server and, when Tether (the per-user session daemon
that owns Aico and A-Term sessions on private tmux servers) is running, in
Tether's session catalog. A tracked session is closed only when neither source
lists it; if Tether's socket exists but does not answer, nothing is closed.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import stat
import subprocess
from pathlib import Path
from typing import Any
from urllib import error, request

AGENT_HUB_API = os.environ.get("AGENT_HUB_API", "http://localhost:8003/api")
ENV_FILE = Path.home() / ".env.local"
STATE_PATH = Path.home() / ".local" / "state" / "tmux-agent-session-sync" / "state.json"
WORKSPACES_ROOT = Path(os.environ.get("ST_WORKSPACES_ROOT", Path.home() / ".local" / "share" / "summitflow" / "workspaces"))
# Prefixes that identify agent tmux sessions (convention: {mode}-{project})
AGENT_PREFIXES = ("claude-", "codex-")
TETHER_TIMEOUT_SECONDS = 3
TETHER_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class TetherUnavailable(Exception):
    """Tether's socket exists but the catalog could not be read."""


def _load_client_id() -> str:
    client_id = ""
    if not ENV_FILE.exists():
        return client_id
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("SUMMITFLOW_CLIENT_ID="):
            client_id = line.split("=", 1)[1].strip().strip('"').strip("'")
    return client_id


def _api_request(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    client_id: str = "",
    request_source: str,
) -> tuple[int | None, str]:
    headers = {
        "X-Request-Source": request_source,
        "X-Source-Client": "summitflow/tmux-agent-session-sync",
        "X-Source-Path": str(Path(__file__)),
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    if client_id:
        headers["X-Client-Id"] = client_id
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    req = request.Request(url, data=payload, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"session_ids": []}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"session_ids": []}


def _save_state(payload: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _git_value(working_dir: str | None, args: list[str]) -> str | None:
    if not working_dir:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", working_dir, *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    return value or None


def _provider_for_mode(mode: str) -> tuple[str, str, str]:
    normalized = (mode or "").lower()
    if normalized == "claude":
        return "anthropic", "external-tmux:claude", "claude_code"
    if normalized == "codex":
        return "codex", "external-tmux:codex", "agent"
    return normalized or "tmux", f"{normalized or 'tmux'}/external-tmux", "agent"


def _resolve_project_root(project_id: str) -> str | None:
    try:
        result = subprocess.run(
            ["st", "projects", "root", project_id],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env={**os.environ, "ST_PROGRESS_ONLY": "1"},
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result and result.returncode == 0:
        resolved = result.stdout.strip()
        if resolved and Path(resolved).is_dir():
            return resolved

    candidate = WORKSPACES_ROOT / "projects" / project_id
    if candidate.is_dir():
        return str(candidate)

    candidate = Path.home() / project_id
    if candidate.is_dir():
        return str(candidate)

    return None


def _session_id(tmux_session_name: str) -> str:
    return f"tmux:{tmux_session_name}"


def _parse_agent_name(name: str) -> tuple[str, str] | None:
    """(mode, project_id) for a `{mode}-{project}` agent session name."""
    if not any(name.startswith(p) for p in AGENT_PREFIXES):
        return None
    mode, _, project_id = name.partition("-")
    return (mode, project_id) if project_id else None


def _tether_socket() -> str:
    if override := os.environ.get("TETHER_SOCKET"):
        return override
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return f"{runtime}/tether/{os.environ.get('TETHER_INSTANCE') or 'default'}/control.sock"


class _TetherConnection(http.client.HTTPConnection):
    def __init__(self, path: str) -> None:
        super().__init__("tether", timeout=TETHER_TIMEOUT_SECONDS)
        self._socket_path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(TETHER_TIMEOUT_SECONDS)
        self.sock.connect(self._socket_path)


def _tether_catalog() -> list[dict[str, Any]] | None:
    """Tether's session descriptors; None when Tether is not installed/running.

    Raises TetherUnavailable when the socket exists but the list cannot be read,
    so the caller can avoid closing sessions it can no longer see.
    """
    path = _tether_socket()
    try:
        info = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISSOCK(info.st_mode):
        return None
    connection = _TetherConnection(path)
    try:
        connection.request("GET", "/v1/sessions")
        response = connection.getresponse()
        body = response.read(TETHER_MAX_RESPONSE_BYTES + 1)
        if response.status != 200 or len(body) > TETHER_MAX_RESPONSE_BYTES:
            raise TetherUnavailable(f"status {response.status}")
        items = json.loads(body).get("items")
    except (OSError, ValueError, AttributeError, http.client.HTTPException) as exc:
        raise TetherUnavailable(str(exc)) from exc
    finally:
        connection.close()
    if not isinstance(items, list):
        raise TetherUnavailable("malformed session list")
    return [item for item in items if isinstance(item, dict)]


def _discover_tether_agent_sessions(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convention-named agent sessions from Tether's catalog (label or tmux name)."""
    sessions = []
    for item in catalog:
        tmux = item.get("tmux") if isinstance(item.get("tmux"), dict) else {}
        for name in (item.get("name"), tmux.get("sessionName")):
            parsed = _parse_agent_name(name) if isinstance(name, str) else None
            if parsed is None:
                continue
            root = item.get("projectRoot")
            sessions.append({
                "tmux_session_name": name,
                "project_id": parsed[1],
                "mode": parsed[0],
                "working_dir": root if isinstance(root, str) and root else _resolve_project_root(parsed[1]),
                "tmux_pane_id": tmux.get("paneId"),
            })
            break
    return sessions


def _discover_agent_tmux_sessions() -> list[dict[str, Any]]:
    """Discover agent tmux sessions directly from the host tmux server."""
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []

    sessions = []
    for name in result.stdout.strip().splitlines():
        name = name.strip()
        # Convention: {mode}-{project} e.g. claude-summitflow, codex-agent-hub
        parsed = _parse_agent_name(name)
        if parsed is None:
            continue
        mode, project_id = parsed

        # Get working directory from the active pane
        try:
            pane_result = subprocess.run(
                ["tmux", "display-message", "-t", name, "-p", "#{pane_current_path}"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            working_dir = pane_result.stdout.strip() or None
        except (OSError, subprocess.TimeoutExpired):
            working_dir = None

        # Fallback: derive from project name
        if not working_dir:
            working_dir = _resolve_project_root(project_id)

        sessions.append({
            "tmux_session_name": name,
            "project_id": project_id,
            "mode": mode,
            "working_dir": working_dir,
        })
    return sessions


def main() -> int:
    client_id = _load_client_id()
    if not client_id:
        return 0

    external_sessions = _discover_agent_tmux_sessions()
    try:
        tether_catalog = _tether_catalog()
        tether_unreadable = False
    except TetherUnavailable:
        tether_catalog, tether_unreadable = None, True
    if tether_catalog is not None:
        seen = {session["tmux_session_name"] for session in external_sessions}
        external_sessions += [session for session in _discover_tether_agent_sessions(tether_catalog)
                              if session["tmux_session_name"] not in seen]
    active_session_ids: list[str] = []

    for session in external_sessions:
        project_id = session["project_id"]
        tmux_session_name = session["tmux_session_name"]
        working_dir = session.get("working_dir")

        current_branch = _git_value(working_dir, ["rev-parse", "--abbrev-ref", "HEAD"])
        repo_root = _git_value(working_dir, ["rev-parse", "--show-toplevel"])
        provider, model, session_type = _provider_for_mode(session["mode"])
        session_id = _session_id(tmux_session_name)
        active_session_ids.append(session_id)

        upsert_body = {
            "session_id": session_id,
            "project_id": project_id,
            "provider": provider,
            "model": model,
            "session_type": session_type,
            "current_branch": current_branch,
            "cwd": working_dir,
            "scope_confidence": "unknown",
            "provider_metadata": {
                "repo_root": repo_root,
                "cwd": working_dir,
                "host": os.uname().nodename,
                "tmux_session_name": tmux_session_name,
                "tmux_pane_id": session.get("tmux_pane_id"),
                "source": "aterm_tmux_sync",
                "external_aterm_session_id": session.get("id"),
            },
        }
        _api_request(
            f"{AGENT_HUB_API}/session-ingestion/sessions/upsert?include_session=false",
            method="POST",
            body=upsert_body,
            client_id=client_id,
            request_source="tmux-agent-session-sync",
        )

        heartbeat_body = {
            "cwd": working_dir,
            "current_branch": current_branch,
            "phase": "running_tool" if session.get("claude_state") == "running" else "waiting_for_model",
            "status": "active",
            "summary": f"tmux session {tmux_session_name} visible via A-Term",
            "current_tool_name": str(session.get("mode") or ""),
            "last_event_type": "heartbeat",
            "provider_metadata": {
                "repo_root": repo_root,
                "cwd": working_dir,
                "host": os.uname().nodename,
                "tmux_session_name": tmux_session_name,
                "tmux_pane_id": session.get("tmux_pane_id"),
                "source": "aterm_tmux_sync",
            },
        }
        _api_request(
            f"{AGENT_HUB_API}/session-ingestion/sessions/{session_id}/heartbeat?include_session=false",
            method="POST",
            body=heartbeat_body,
            client_id=client_id,
            request_source="tmux-agent-session-sync",
        )

    previous = set(_state().get("session_ids", []))
    current = set(active_session_ids)
    if tether_unreadable:
        # Tether is installed but did not answer: its sessions may still be live.
        _save_state({"session_ids": sorted(previous | current)})
        return 0
    for stale_session_id in sorted(previous - current):
        _api_request(
            f"{AGENT_HUB_API}/sessions/{stale_session_id}/close",
            method="POST",
            client_id=client_id,
            request_source="tmux-agent-session-sync",
        )

    _save_state({"session_ids": sorted(current)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
