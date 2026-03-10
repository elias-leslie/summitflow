#!/usr/bin/env python3
"""Sync external tmux agent sessions from Terminal into Agent Hub."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib import error, request

TERMINAL_API = os.environ.get("TERMINAL_API", "http://localhost:8002/api/terminal/sessions")
AGENT_HUB_API = os.environ.get("AGENT_HUB_API", "http://localhost:8003/api")
ENV_FILE = Path.home() / ".env.local"
STATE_PATH = Path.home() / ".local" / "state" / "tmux-agent-session-sync" / "state.json"


def _load_credentials() -> tuple[str, str]:
    client_id = ""
    client_secret = ""
    if not ENV_FILE.exists():
        return client_id, client_secret
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("SUMMITFLOW_CLIENT_ID="):
            client_id = line.split("=", 1)[1].strip().strip('"').strip("'")
        elif line.startswith("SUMMITFLOW_CLIENT_SECRET="):
            client_secret = line.split("=", 1)[1].strip().strip('"').strip("'")
    return client_id, client_secret


def _api_request(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    client_id: str = "",
    client_secret: str = "",
    request_source: str,
) -> tuple[int | None, str]:
    headers = {
        "X-Request-Source": request_source,
        "X-Source-Client": "summitflow/tmux-agent-session-sync",
        "X-Source-Path": str(Path(__file__)),
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    if client_id and client_secret:
        headers["X-Client-Id"] = client_id
        headers["X-Client-Secret"] = client_secret
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    req = request.Request(url, data=payload, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _get_json(url: str) -> dict[str, Any]:
    status, payload = _api_request(url, request_source="tmux-agent-session-sync")
    if status != 200:
        raise RuntimeError(f"GET {url} failed: status={status} body={payload[:200]}")
    decoded = json.loads(payload)
    if not isinstance(decoded, dict):
        raise RuntimeError(f"Unexpected JSON payload from {url}")
    return decoded


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
        return "anthropic", "claude/external-tmux", "claude_code"
    if normalized == "codex":
        return "codex", "codex/external-tmux", "agent"
    return normalized or "tmux", f"{normalized or 'tmux'}/external-tmux", "agent"


def _session_id(tmux_session_name: str) -> str:
    return f"tmux:{tmux_session_name}"


def main() -> int:
    client_id, client_secret = _load_credentials()
    if not client_id or not client_secret:
        return 0

    sessions_payload = _get_json(TERMINAL_API)
    items = sessions_payload.get("items", [])
    if not isinstance(items, list):
        return 0

    external_sessions = [row for row in items if isinstance(row, dict) and row.get("is_external")]
    active_session_ids: list[str] = []

    for session in external_sessions:
        project_id = session.get("project_id")
        tmux_session_name = session.get("tmux_session_name")
        working_dir = session.get("working_dir")
        if not isinstance(project_id, str) or not project_id or not isinstance(tmux_session_name, str):
            continue

        current_branch = _git_value(working_dir if isinstance(working_dir, str) else None, ["rev-parse", "--abbrev-ref", "HEAD"])
        repo_root = _git_value(working_dir if isinstance(working_dir, str) else None, ["rev-parse", "--show-toplevel"])
        provider, model, session_type = _provider_for_mode(str(session.get("mode") or ""))
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
                "worktree_path": working_dir,
                "host": os.uname().nodename,
                "tmux_session_name": tmux_session_name,
                "tmux_pane_id": session.get("tmux_pane_id"),
                "source": "terminal_tmux_sync",
                "external_terminal_session_id": session.get("id"),
            },
        }
        _api_request(
            f"{AGENT_HUB_API}/session-ingestion/sessions/upsert",
            method="POST",
            body=upsert_body,
            client_id=client_id,
            client_secret=client_secret,
            request_source="tmux-agent-session-sync",
        )

        heartbeat_body = {
            "cwd": working_dir,
            "current_branch": current_branch,
            "phase": "running_tool" if session.get("claude_state") == "running" else "waiting_for_model",
            "status": "active",
            "summary": f"tmux session {tmux_session_name} visible via Terminal",
            "current_tool_name": str(session.get("mode") or ""),
            "last_event_type": "heartbeat",
            "provider_metadata": {
                "repo_root": repo_root,
                "worktree_path": working_dir,
                "host": os.uname().nodename,
                "tmux_session_name": tmux_session_name,
                "tmux_pane_id": session.get("tmux_pane_id"),
                "source": "terminal_tmux_sync",
            },
        }
        _api_request(
            f"{AGENT_HUB_API}/sessions/{session_id}/heartbeat",
            method="POST",
            body=heartbeat_body,
            client_id=client_id,
            client_secret=client_secret,
            request_source="tmux-agent-session-sync",
        )

    previous = set(_state().get("session_ids", []))
    current = set(active_session_ids)
    for stale_session_id in sorted(previous - current):
        _api_request(
            f"{AGENT_HUB_API}/sessions/{stale_session_id}/close",
            method="POST",
            client_id=client_id,
            client_secret=client_secret,
            request_source="tmux-agent-session-sync",
        )

    _save_state({"session_ids": sorted(current)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
