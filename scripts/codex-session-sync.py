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
from typing import Any
from urllib import error, request


DEFAULT_API = os.environ.get("AGENT_HUB_API", "http://localhost:8003/api")
STATE_PATH = Path.home() / ".local" / "state" / "codex-session-sync" / "state.json"
LOG_PATH = Path.home() / ".codex" / "hooks" / "codex-session-sync.log"
TRANSCRIPTS_ROOT = Path.home() / ".codex" / "sessions"
ENV_FILE = Path.home() / ".env.local"

PROVIDER = "codex"
SESSION_TYPE = "agent"
DEFAULT_MODEL = "gpt-5.4"
GIT_LOG_WINDOW = "12 hours ago"
REQUEST_SOURCE = "codex-transcript-sync"
ENV_CLIENT_ID = "SUMMITFLOW_CLIENT_ID="
ENV_CLIENT_SECRET = "SUMMITFLOW_CLIENT_SECRET="


@dataclass(frozen=True)
class TranscriptInfo:
    path: Path
    session_id: str
    cwd: Path
    model: str
    mtime: float
    size: int


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
        if line.startswith(ENV_CLIENT_ID):
            client_id = _parse_env_value(line.split("=", 1)[1])
        elif line.startswith(ENV_CLIENT_SECRET):
            client_secret = _parse_env_value(line.split("=", 1)[1])
    return client_id, client_secret


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"transcripts": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"transcripts": {}}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def read_transcript_info(path: Path) -> TranscriptInfo | None:
    session_id = ""
    cwd = ""
    model = ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        log(f"[WARN] Failed to read transcript {path}: {exc}")
        return None
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        obj_type = obj.get("type")
        payload = obj.get("payload") or {}
        if obj_type == "session_meta":
            session_id = payload.get("id") or session_id
            cwd = payload.get("cwd") or cwd
        elif obj_type == "turn_context" and not model:
            model = payload.get("model") or model
        if session_id and cwd and model:
            break
    if not session_id or not cwd:
        return None
    stat = path.stat()
    return TranscriptInfo(
        path=path,
        session_id=session_id,
        cwd=Path(cwd),
        model=model or DEFAULT_MODEL,
        mtime=stat.st_mtime,
        size=stat.st_size,
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


def build_project_context(cwd: Path) -> dict[str, Any] | None:
    try:
        project_dir = subprocess.check_output(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
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
         f"--since={GIT_LOG_WINDOW}", "--no-merges", "--format=%h %s"],
        capture_output=True, text=True, check=False,
    ).stdout
    git_lines = [
        ln for ln in raw_log.splitlines()
        if not ln.startswith(" chore: auto-fix") and "chore(.index" not in ln
    ]
    return {
        "project_dir": project_path,
        "project_id": project_path.name,
        "branch": branch,
        "is_worktree": (project_path / ".git").is_file(),
        "git_context": "\n".join(git_lines[:10]),
    }


def post_json(
    api_url: str,
    endpoint: str,
    body: dict[str, Any] | None,
    client_id: str,
    client_secret: str,
) -> tuple[int | None, str]:
    headers = {
        "Content-Type": "application/json",
        "X-Client-Id": client_id,
        "X-Client-Secret": client_secret,
        "X-Request-Source": REQUEST_SOURCE,
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = request.Request(
        f"{api_url.rstrip('/')}/{endpoint.lstrip('/')}",
        data=data, headers=headers, method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8")
    except error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _api_post(
    api_url: str, endpoint: str, body: dict[str, Any] | None,
    client_id: str, client_secret: str, label: str,
) -> tuple[bool, str, str]:
    """POST to endpoint; return (ok, error_detail, raw_payload)."""
    status, payload = post_json(api_url, endpoint, body, client_id, client_secret)
    if status != 200:
        return False, f"{label} failed status={status} body={payload[:300]}", ""
    return True, "", payload


def _upsert_session(
    info: TranscriptInfo, project: dict[str, Any],
    api_url: str, client_id: str, client_secret: str,
) -> tuple[bool, str]:
    ok, detail, _ = _api_post(api_url, "/session-ingestion/sessions/upsert", {
        "session_id": info.session_id, "project_id": project["project_id"],
        "provider": PROVIDER, "model": f"{PROVIDER}/{info.model}",
        "session_type": SESSION_TYPE, "cwd": str(info.cwd),
        "current_branch": project["branch"],
        "provider_metadata": {"transcript_path": str(info.path)},
    }, client_id, client_secret, "session upsert")
    return ok, detail


def _ingest_events(
    info: TranscriptInfo, state: dict[str, Any],
    api_url: str, client_id: str, client_secret: str,
) -> tuple[bool, str, dict[str, Any]]:
    checkpoint = state.get("transcripts", {}).get(str(info.path), {}).get("checkpoint")
    ok, detail, payload = _api_post(
        api_url, f"/session-ingestion/sessions/{info.session_id}/transcript-events",
        {"provider": PROVIDER, "transcript_path": str(info.path), "checkpoint": checkpoint},
        client_id, client_secret, "transcript ingest",
    )
    return (ok, detail, json.loads(payload)) if ok else (False, detail, {})


def _finalize_session(
    session_id: str, project: dict[str, Any],
    api_url: str, client_id: str, client_secret: str,
) -> tuple[bool, str]:
    ok, detail, _ = _api_post(
        api_url, f"/session-ingestion/sessions/{session_id}/finalize",
        {"branch": project["branch"], "git_context": project["git_context"],
         "is_worktree": project["is_worktree"]},
        client_id, client_secret, "finalize",
    )
    return ok, detail


def sync_transcript(
    info: TranscriptInfo,
    state: dict[str, Any],
    api_url: str,
    client_id: str,
    client_secret: str,
    close_session: bool,
    verbose: bool,
) -> tuple[bool, str]:
    project = build_project_context(info.cwd)
    if project is None:
        return False, f"skip non-git cwd={info.cwd}"

    ok, detail = _upsert_session(info, project, api_url, client_id, client_secret)
    if not ok:
        return False, detail

    ok, detail, ingest_data = _ingest_events(info, state, api_url, client_id, client_secret)
    if not ok:
        return False, detail
    update_state_entry(
        state, info, "synced",
        f"appended={ingest_data.get('events_appended', 0)} skipped={ingest_data.get('events_skipped', 0)}",
        checkpoint=ingest_data.get("next_checkpoint"),
    )

    ok, detail = _finalize_session(info.session_id, project, api_url, client_id, client_secret)
    if not ok:
        return False, detail

    if close_session:
        ok, detail, _ = _api_post(api_url, f"/sessions/{info.session_id}/close",
                                   None, client_id, client_secret, "close")
        if not ok:
            return False, detail

    if verbose:
        log(f"[INFO] Synced session={info.session_id} project={project['project_id']} "
            f"transcript={info.path} close={close_session}")
    return True, "ok"


def should_sync(info: TranscriptInfo, state: dict[str, Any], force: bool) -> bool:
    if force:
        return True
    entry = state.get("transcripts", {}).get(str(info.path))
    if not isinstance(entry, dict):
        return True
    return entry.get("mtime") != info.mtime or entry.get("size") != info.size


def update_state_entry(
    state: dict[str, Any],
    info: TranscriptInfo,
    status: str,
    detail: str,
    checkpoint: str | None = None,
) -> None:
    state.setdefault("transcripts", {})[str(info.path)] = {
        "session_id": info.session_id,
        "mtime": info.mtime,
        "size": info.size,
        "status": status,
        "detail": detail,
        "checkpoint": checkpoint,
        "updated_at": datetime.now(UTC).isoformat(),
    }


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
        infos = [info] if info is not None else []
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
