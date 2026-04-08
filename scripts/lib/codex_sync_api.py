"""HTTP helpers and sync steps for codex-session-sync."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib import error, request

HTTP_TIMEOUT = 20

HEADER_CONTENT_TYPE = "Content-Type"
HEADER_CLIENT_ID = "X-Client-Id"
HEADER_CLIENT_SECRET = "X-Client-Secret"
HEADER_REQUEST_SOURCE = "X-Request-Source"
HEADER_SOURCE_CLIENT = "X-Source-Client"
HEADER_SOURCE_PATH = "X-Source-Path"

ENDPOINT_UPSERT = "/session-ingestion/sessions/upsert?include_session=false"
ENDPOINT_TRANSCRIPT = "/session-ingestion/sessions/{sid}/transcript-events"
ENDPOINT_HEARTBEAT = "/session-ingestion/sessions/{sid}/heartbeat?include_session=false"
ENDPOINT_FINALIZE = "/session-ingestion/sessions/{sid}/finalize"
ENDPOINT_CLOSE = "/sessions/{sid}/close"

REQUEST_SOURCE = "codex-transcript-sync"
SOURCE_CLIENT = "summitflow/codex-session-sync"
PROVIDER = "codex"
SESSION_TYPE = "agent"
SCOPE_CONFIDENCE = "unknown"
HEARTBEAT_PHASE = "waiting_for_model"
HEARTBEAT_STATUS = "active"
HEARTBEAT_EVENT_TYPE = "heartbeat"


def post_json(
    api_url: str,
    endpoint: str,
    body: dict[str, object] | None,
    client_id: str,
    client_secret: str,
    source_path: str = "",
) -> tuple[int | None, str]:
    headers = {
        HEADER_CONTENT_TYPE: "application/json",
        HEADER_CLIENT_ID: client_id,
        HEADER_CLIENT_SECRET: client_secret,
        HEADER_REQUEST_SOURCE: REQUEST_SOURCE,
        HEADER_SOURCE_CLIENT: SOURCE_CLIENT,
        HEADER_SOURCE_PATH: source_path,
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None
    url = f"{api_url.rstrip('/')}/{endpoint.lstrip('/')}"
    req = request.Request(url, data=data, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8")
    except error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _checked_post(
    api_url: str,
    endpoint: str,
    body: dict[str, object] | None,
    client_id: str,
    client_secret: str,
    label: str,
    source_path: str = "",
) -> tuple[bool, str, str, int | None]:
    """Return (ok, response_body, error_msg, status_code)."""
    status, payload = post_json(api_url, endpoint, body, client_id, client_secret, source_path)
    if status != 200:
        return False, payload, f"{label} failed status={status} body={payload[:300]}", status
    return True, payload, "", status


def upsert_session(
    session_id: str,
    project: dict[str, object],
    model: str,
    cwd: Path,
    transcript_path: Path,
    api_url: str,
    client_id: str,
    client_secret: str,
    source_path: str = "",
) -> tuple[bool, str, int | None]:
    ok, _, err, status = _checked_post(
        api_url,
        ENDPOINT_UPSERT,
        {
            "session_id": session_id,
            "project_id": project["project_id"],
            "provider": PROVIDER,
            "model": f"{PROVIDER}/{model}",
            "session_type": SESSION_TYPE,
            "cwd": str(cwd),
            "current_branch": project["branch"],
            "scope_confidence": SCOPE_CONFIDENCE,
            "provider_metadata": {
                "transcript_path": str(transcript_path),
                "repo_root": project["repo_root"],
                "worktree_path": str(cwd),
                "host": os.uname().nodename,
            },
        },
        client_id,
        client_secret,
        "session upsert",
        source_path,
    )
    return ok, err, status


def ingest_transcript(
    session_id: str,
    transcript_path: Path,
    checkpoint: str | None,
    api_url: str,
    client_id: str,
    client_secret: str,
    source_path: str = "",
) -> tuple[bool, str | None, str, str, int | None]:
    """Return (ok, next_checkpoint, ingest_detail, error_msg, status_code)."""
    ok, payload, err, status = _checked_post(
        api_url,
        ENDPOINT_TRANSCRIPT.format(sid=session_id),
        {"provider": PROVIDER, "transcript_path": str(transcript_path), "checkpoint": checkpoint},
        client_id,
        client_secret,
        "transcript ingest",
        source_path,
    )
    if not ok:
        return False, None, "", err, status
    try:
        ingest_data = json.loads(payload)
    except json.JSONDecodeError as exc:
        return False, None, "", f"transcript ingest returned invalid JSON: {exc}", status
    next_cp = ingest_data.get("next_checkpoint")
    detail = (
        f"appended={ingest_data.get('events_appended', 0)}"
        f" skipped={ingest_data.get('events_skipped', 0)}"
    )
    return True, str(next_cp) if next_cp else None, detail, "", status


def send_heartbeat(
    session_id: str,
    cwd: Path,
    project: dict[str, object],
    meta: dict[str, object],
    api_url: str,
    client_id: str,
    client_secret: str,
    source_path: str = "",
) -> tuple[bool, str, int | None]:
    ok, _, err, status = _checked_post(
        api_url,
        ENDPOINT_HEARTBEAT.format(sid=session_id),
        {
            "cwd": str(cwd),
            "current_branch": project["branch"],
            "phase": HEARTBEAT_PHASE,
            "status": HEARTBEAT_STATUS,
            "summary": f"Transcript sync heartbeat for {session_id}",
            "last_event_type": HEARTBEAT_EVENT_TYPE,
            "provider_metadata": meta,
        },
        client_id,
        client_secret,
        "heartbeat",
        source_path,
    )
    return ok, err, status


def finalize_and_close(
    session_id: str,
    project: dict[str, object],
    close_session: bool,
    api_url: str,
    client_id: str,
    client_secret: str,
    source_path: str = "",
) -> tuple[bool, str, int | None]:
    ok, _, err, status = _checked_post(
        api_url,
        ENDPOINT_FINALIZE.format(sid=session_id),
        {
            "branch": project["branch"],
            "git_context": project["git_context"],
            "is_worktree": project["is_worktree"],
        },
        client_id,
        client_secret,
        "finalize",
        source_path,
    )
    if not ok:
        return False, err, status
    if not close_session:
        return True, "", status
    ok, _, err, status = _checked_post(
        api_url,
        ENDPOINT_CLOSE.format(sid=session_id),
        None,
        client_id,
        client_secret,
        "close",
        source_path,
    )
    return ok, err, status
