#!/usr/bin/env python3
"""Sync Codex transcript analysis into Agent Hub without waiting for process exit."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib import error, request

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_API = os.environ.get("AGENT_HUB_API", "http://localhost:8003/api")
STATE_PATH = Path.home() / ".local" / "state" / "codex-session-sync" / "state.json"
LOG_PATH = Path.home() / ".codex" / "session-integrations" / "codex-session-sync.log"
TRANSCRIPTS_ROOT = Path.home() / ".codex" / "sessions"
ENV_FILE = Path.home() / ".env.local"

ENV_KEY_CLIENT_ID = "SUMMITFLOW_CLIENT_ID"
ENV_KEY_CLIENT_SECRET = "SUMMITFLOW_CLIENT_SECRET"
DEFAULT_MODEL = "gpt-5.4"
GIT_LOG_SINCE = "12 hours ago"
GIT_LOG_LIMIT = 10
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

GIT_FILTER_PREFIXES = ("chore: auto-fix", "chore(.index")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TranscriptInfo:
    path: Path
    session_id: str
    cwd: Path
    model: str
    mtime: float
    size: int


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat()
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")


def _parse_env_value(raw: str) -> str:
    stripped = raw.rstrip()
    if len(stripped) >= 2 and stripped[0] in ("'", '"') and stripped.endswith(stripped[0]):
        return stripped[1:-1]
    return raw.split("#")[0].strip()


def load_env_credentials() -> tuple[str, str]:
    if not ENV_FILE.exists():
        return "", ""
    client_id = ""
    client_secret = ""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{ENV_KEY_CLIENT_ID}="):
            client_id = _parse_env_value(line.split("=", 1)[1])
        elif line.startswith(f"{ENV_KEY_CLIENT_SECRET}="):
            client_secret = _parse_env_value(line.split("=", 1)[1])
    return client_id, client_secret


def load_state() -> dict[str, object]:
    if not STATE_PATH.exists():
        return {"transcripts": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))  # type: ignore[return-value]
    except json.JSONDecodeError:
        return {"transcripts": {}}


def save_state(state: dict[str, object]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# Transcript discovery
# ---------------------------------------------------------------------------


def _parse_transcript_line(
    obj: dict[str, object], session_id: str, cwd: str, model: str
) -> tuple[str, str, str]:
    obj_type = obj.get("type")
    payload = obj.get("payload") or {}
    if not isinstance(payload, dict):
        return session_id, cwd, model
    if obj_type == "session_meta":
        session_id = str(payload.get("id") or session_id)
        cwd = str(payload.get("cwd") or cwd)
    elif obj_type == "turn_context" and not model:
        model = str(payload.get("model") or model)
    return session_id, cwd, model


def _parse_jsonl_line(line: str) -> dict[str, object] | None:
    try:
        return json.loads(line)  # type: ignore[return-value]
    except json.JSONDecodeError:
        return None


def _scan_transcript_headers(path: Path) -> tuple[str, str, str]:
    """Return (session_id, cwd, model) from early lines of a transcript."""
    session_id = cwd = model = ""
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= 100:
                break
            obj = _parse_jsonl_line(line)
            if obj is not None:
                session_id, cwd, model = _parse_transcript_line(obj, session_id, cwd, model)
            if session_id and cwd and model:
                break
    return session_id, cwd, model


def read_transcript_info(path: Path) -> TranscriptInfo | None:
    try:
        session_id, cwd, model = _scan_transcript_headers(path)
    except OSError as exc:
        log(f"[WARN] Failed to read transcript {path}: {exc}")
        return None
    if not session_id or not cwd:
        return None
    stat = path.stat()
    return TranscriptInfo(
        path=path, session_id=session_id, cwd=Path(cwd),
        model=model or DEFAULT_MODEL, mtime=stat.st_mtime, size=stat.st_size,
    )


def iter_recent_transcripts(recent_hours: int) -> list[TranscriptInfo]:
    if not TRANSCRIPTS_ROOT.exists():
        return []
    cutoff = datetime.now(UTC) - timedelta(hours=recent_hours)
    transcripts: list[TranscriptInfo] = []
    for path in TRANSCRIPTS_ROOT.rglob("*.jsonl"):
        try:
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        except OSError:
            continue
        if modified_at < cutoff:
            continue
        info = read_transcript_info(path)
        if info is not None:
            transcripts.append(info)
    transcripts.sort(key=lambda item: item.mtime)
    return transcripts


# ---------------------------------------------------------------------------
# Git context
# ---------------------------------------------------------------------------


def build_project_context(cwd: Path) -> dict[str, object] | None:
    try:
        project_dir = subprocess.check_output(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return None
    project_path = Path(project_dir)
    branch = subprocess.run(
        ["git", "-C", str(project_path), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    raw_log = subprocess.run(
        ["git", "-C", str(project_path), "log", "--oneline",
         f"--since={GIT_LOG_SINCE}", "--no-merges", "--format=%h %s"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    git_lines = [
        ln for ln in raw_log.splitlines()
        if not any(ln.startswith(p) or p in ln for p in GIT_FILTER_PREFIXES)
    ]
    return {
        "project_dir": project_path,
        "project_id": project_path.name,
        "branch": branch,
        "is_worktree": (project_path / ".git").is_file(),
        "repo_root": str(project_path),
        "git_context": "\n".join(git_lines[:GIT_LOG_LIMIT]),
    }


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def post_json(
    api_url: str, endpoint: str, body: dict[str, object] | None,
    client_id: str, client_secret: str,
) -> tuple[int | None, str]:
    headers = {
        HEADER_CONTENT_TYPE: "application/json",
        HEADER_CLIENT_ID: client_id,
        HEADER_CLIENT_SECRET: client_secret,
        HEADER_REQUEST_SOURCE: REQUEST_SOURCE,
        HEADER_SOURCE_CLIENT: SOURCE_CLIENT,
        HEADER_SOURCE_PATH: str(Path(__file__)),
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
    api_url: str, endpoint: str, body: dict[str, object] | None,
    client_id: str, client_secret: str, label: str,
) -> tuple[bool, str, str]:
    """Return (ok, response_body, error_msg)."""
    status, payload = post_json(api_url, endpoint, body, client_id, client_secret)
    if status != 200:
        return False, payload, f"{label} failed status={status} body={payload[:300]}"
    return True, payload, ""


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


def update_state_entry(
    state: dict[str, object], info: TranscriptInfo,
    status: str, detail: str, checkpoint: str | None = None,
) -> None:
    transcripts = state.setdefault("transcripts", {})
    if not isinstance(transcripts, dict):
        state["transcripts"] = {}
        transcripts = state["transcripts"]
    transcripts[str(info.path)] = {
        "session_id": info.session_id,
        "mtime": info.mtime,
        "size": info.size,
        "status": status,
        "detail": detail,
        "checkpoint": checkpoint,
        "updated_at": datetime.now(UTC).isoformat(),
    }


def should_sync(info: TranscriptInfo, state: dict[str, object], force: bool) -> bool:
    if force:
        return True
    entries = state.get("transcripts") or {}
    if not isinstance(entries, dict):
        return True
    entry = entries.get(str(info.path))
    if not isinstance(entry, dict):
        return True
    return entry.get("mtime") != info.mtime or entry.get("size") != info.size


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------


def _build_meta(info: TranscriptInfo, project: dict[str, object]) -> dict[str, object]:
    return {
        "transcript_path": str(info.path),
        "repo_root": project["repo_root"],
        "worktree_path": str(info.cwd),
        "host": os.uname().nodename,
    }


def _get_checkpoint(state: dict[str, object], info: TranscriptInfo) -> str | None:
    ts = state.get("transcripts") or {}
    if not isinstance(ts, dict):
        return None
    entry = ts.get(str(info.path))
    return entry.get("checkpoint") if isinstance(entry, dict) else None  # type: ignore[return-value]


def _upsert_session(
    api_url: str, info: TranscriptInfo, project: dict[str, object],
    client_id: str, client_secret: str,
) -> tuple[bool, str]:
    """Register or update the Agent Hub session."""
    ok, _, err = _checked_post(api_url, ENDPOINT_UPSERT, {
        "session_id": info.session_id, "project_id": project["project_id"],
        "provider": PROVIDER, "model": f"{PROVIDER}/{info.model}",
        "session_type": SESSION_TYPE, "cwd": str(info.cwd),
        "current_branch": project["branch"], "scope_confidence": SCOPE_CONFIDENCE,
        "provider_metadata": _build_meta(info, project),
    }, client_id, client_secret, "session upsert")
    return ok, err


def _ingest_transcript(
    api_url: str, info: TranscriptInfo, state: dict[str, object],
    client_id: str, client_secret: str,
) -> tuple[bool, str, str | None]:
    """Send transcript events and return (ok, error, checkpoint)."""
    ok, payload, err = _checked_post(
        api_url, ENDPOINT_TRANSCRIPT.format(sid=info.session_id),
        {"provider": PROVIDER, "transcript_path": str(info.path),
         "checkpoint": _get_checkpoint(state, info)},
        client_id, client_secret, "transcript ingest",
    )
    if not ok:
        return False, err, None
    try:
        ingest_data = json.loads(payload)
    except json.JSONDecodeError as exc:
        return False, f"transcript ingest returned invalid JSON: {exc}", None

    next_cp = ingest_data.get("next_checkpoint")
    checkpoint = str(next_cp) if next_cp else None
    update_state_entry(
        state, info, "synced",
        f"appended={ingest_data.get('events_appended', 0)} skipped={ingest_data.get('events_skipped', 0)}",
        checkpoint=checkpoint,
    )
    return True, "", checkpoint


def _send_heartbeat_and_finalize(
    api_url: str, info: TranscriptInfo, project: dict[str, object],
    client_id: str, client_secret: str,
) -> tuple[bool, str]:
    """Send heartbeat and finalize calls."""
    ok, _, err = _checked_post(api_url, ENDPOINT_HEARTBEAT.format(sid=info.session_id), {
        "cwd": str(info.cwd), "current_branch": project["branch"],
        "phase": HEARTBEAT_PHASE, "status": HEARTBEAT_STATUS,
        "summary": f"Transcript sync heartbeat for {info.session_id}",
        "last_event_type": HEARTBEAT_EVENT_TYPE, "provider_metadata": _build_meta(info, project),
    }, client_id, client_secret, "heartbeat")
    if not ok:
        return False, err

    ok, _, err = _checked_post(api_url, ENDPOINT_FINALIZE.format(sid=info.session_id), {
        "branch": project["branch"], "git_context": project["git_context"],
        "is_worktree": project["is_worktree"],
    }, client_id, client_secret, "finalize")
    return ok, err


def sync_transcript(
    info: TranscriptInfo, state: dict[str, object], api_url: str,
    client_id: str, client_secret: str, close_session: bool, verbose: bool,
) -> tuple[bool, str]:
    project = build_project_context(info.cwd)
    if project is None:
        return False, f"skip non-git cwd={info.cwd}"

    ok, err = _upsert_session(api_url, info, project, client_id, client_secret)
    if not ok:
        return False, err

    ok, err, _checkpoint = _ingest_transcript(api_url, info, state, client_id, client_secret)
    if not ok:
        return False, err

    ok, err = _send_heartbeat_and_finalize(api_url, info, project, client_id, client_secret)
    if not ok:
        return False, err

    if close_session:
        ok, _, err = _checked_post(
            api_url, ENDPOINT_CLOSE.format(sid=info.session_id),
            None, client_id, client_secret, "close",
        )
        if not ok:
            return False, err

    if verbose:
        log(f"[INFO] Synced session={info.session_id} project={project['project_id']} "
            f"transcript={info.path} close={close_session}")
    return True, "ok"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", action="store_true", help="Scan recent Codex transcripts")
    parser.add_argument("--transcript", type=Path, help="Sync a specific transcript path")
    parser.add_argument("--recent-hours", type=int, default=24, help="Recent hours to scan")
    parser.add_argument("--close", action="store_true", help="Close the Agent Hub session after analysis")
    parser.add_argument("--force", action="store_true", help="Sync even if transcript state is unchanged")
    parser.add_argument("--verbose", action="store_true", help="Write success entries to the sync log")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if not args.scan and args.transcript is None:
        args.scan = True

    client_id, client_secret = load_env_credentials()
    if not client_id or not client_secret:
        log("[WARN] Missing SUMMITFLOW_CLIENT_ID or SUMMITFLOW_CLIENT_SECRET; skipping Codex sync")
        return 0

    state = load_state()
    if args.transcript is not None:
        info = read_transcript_info(args.transcript)
        infos: list[TranscriptInfo] = [info] if info is not None else []
    else:
        infos = iter_recent_transcripts(args.recent_hours)

    for info in infos:
        if not should_sync(info, state, args.force):
            continue
        ok, detail = sync_transcript(
            info=info, state=state, api_url=DEFAULT_API,
            client_id=client_id, client_secret=client_secret,
            close_session=args.close, verbose=args.verbose,
        )
        if not ok:
            update_state_entry(state, info, "error", detail)
            log(f"[WARN] Failed sync for {info.path}: {detail}")

    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
