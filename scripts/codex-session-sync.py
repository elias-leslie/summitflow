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


def load_env_credentials() -> tuple[str, str]:
    client_id = ""
    client_secret = ""
    if not ENV_FILE.exists():
        return client_id, client_secret

    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("SUMMITFLOW_CLIENT_ID="):
            raw_value = line.split("=", 1)[1]
            if len(raw_value) >= 2 and raw_value[0] in ("'", '"') and raw_value.rstrip().endswith(raw_value[0]):
                value = raw_value.rstrip()[1:-1]
            else:
                value = raw_value.split("#")[0].strip()
            client_id = value
        elif line.startswith("SUMMITFLOW_CLIENT_SECRET="):
            raw_value = line.split("=", 1)[1]
            if len(raw_value) >= 2 and raw_value[0] in ("'", '"') and raw_value.rstrip().endswith(raw_value[0]):
                value = raw_value.rstrip()[1:-1]
            else:
                value = raw_value.split("#")[0].strip()
            client_secret = value
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
        with path.open(encoding="utf-8") as handle:
            for line in handle:
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
    except OSError as exc:
        log(f"[WARN] Failed to read transcript {path}: {exc}")
        return None

    if not session_id or not cwd:
        return None

    stat = path.stat()
    return TranscriptInfo(
        path=path,
        session_id=session_id,
        cwd=Path(cwd),
        model=model or "gpt-5.4",
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
    project_id = project_path.name
    current_branch = subprocess.run(
        ["git", "-C", str(project_path), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    git_context = subprocess.run(
        [
            "git",
            "-C",
            str(project_path),
            "log",
            "--oneline",
            '--since=12 hours ago',
            "--no-merges",
            "--format=%h %s",
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    git_lines = [
        line
        for line in git_context.splitlines()
        if not line.startswith(" chore: auto-fix")
        and "chore(.index" not in line
    ]
    return {
        "project_dir": project_path,
        "project_id": project_id,
        "branch": current_branch,
        "is_worktree": (project_path / ".git").is_file(),
        "repo_root": str(project_path),
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
        "X-Request-Source": "codex-transcript-sync",
        "X-Source-Client": "summitflow/codex-session-sync",
        "X-Source-Path": str(Path(__file__)),
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = request.Request(f"{api_url.rstrip('/')}/{endpoint.lstrip('/')}", data=data, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=20) as resp:
            payload = resp.read().decode("utf-8")
            return resp.status, payload
    except error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        return exc.code, payload
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


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

    create_body = {
        "session_id": info.session_id,
        "project_id": project["project_id"],
        "provider": "codex",
        "model": f"codex/{info.model}",
        "session_type": "agent",
        "cwd": str(info.cwd),
        "current_branch": project["branch"],
        "scope_confidence": "unknown",
        "provider_metadata": {
            "transcript_path": str(info.path),
            "repo_root": project["repo_root"],
            "worktree_path": str(info.cwd),
            "host": os.uname().nodename,
        },
    }
    status, payload = post_json(
        api_url,
        "/session-ingestion/sessions/upsert",
        create_body,
        client_id,
        client_secret,
    )
    if status != 200:
        return False, f"session upsert failed status={status} body={payload[:300]}"

    transcript_state = state.get("transcripts", {}).get(str(info.path), {})
    ingest_body = {
        "provider": "codex",
        "transcript_path": str(info.path),
        "checkpoint": transcript_state.get("checkpoint"),
    }
    status, payload = post_json(
        api_url,
        f"/session-ingestion/sessions/{info.session_id}/transcript-events",
        ingest_body,
        client_id,
        client_secret,
    )
    if status != 200:
        return False, f"transcript ingest failed status={status} body={payload[:300]}"

    ingest_data = json.loads(payload)
    update_state_entry(
        state,
        info,
        "synced",
        (
            f"appended={ingest_data.get('events_appended', 0)} "
            f"skipped={ingest_data.get('events_skipped', 0)}"
        ),
        checkpoint=ingest_data.get("next_checkpoint"),
    )

    heartbeat_body = {
        "cwd": str(info.cwd),
        "current_branch": project["branch"],
        "phase": "waiting_for_model",
        "status": "active",
        "summary": f"Transcript sync heartbeat for {info.session_id}",
        "last_event_type": "heartbeat",
        "provider_metadata": {
            "transcript_path": str(info.path),
            "repo_root": project["repo_root"],
            "worktree_path": str(info.cwd),
            "host": os.uname().nodename,
        },
    }
    status, payload = post_json(
        api_url,
        f"/sessions/{info.session_id}/heartbeat",
        heartbeat_body,
        client_id,
        client_secret,
    )
    if status != 200:
        return False, f"heartbeat failed status={status} body={payload[:300]}"

    finalize_body = {
        "branch": project["branch"],
        "git_context": project["git_context"],
        "is_worktree": project["is_worktree"],
    }
    status, payload = post_json(
        api_url,
        f"/session-ingestion/sessions/{info.session_id}/finalize",
        finalize_body,
        client_id,
        client_secret,
    )
    if status != 200:
        return False, f"finalize failed status={status} body={payload[:300]}"

    if close_session:
        status, payload = post_json(
            api_url,
            f"/sessions/{info.session_id}/close",
            None,
            client_id,
            client_secret,
        )
        if status != 200:
            return False, f"close failed status={status} body={payload[:300]}"

    if verbose:
        log(
            "[INFO] Synced "
            f"session={info.session_id} project={project['project_id']} "
            f"transcript={info.path} close={close_session}"
        )
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
    transcripts = state.setdefault("transcripts", {})
    transcripts[str(info.path)] = {
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
        infos = []
        info = read_transcript_info(args.transcript)
        if info is not None:
            infos.append(info)
    else:
        infos = iter_recent_transcripts(args.recent_hours)

    for info in infos:
        if not should_sync(info, state, args.force):
            continue
        ok, detail = sync_transcript(
            info=info,
            state=state,
            api_url=DEFAULT_API,
            client_id=client_id,
            client_secret=client_secret,
            close_session=args.close,
            verbose=args.verbose,
        )
        if not ok:
            update_state_entry(state, info, "error", detail)
            log(f"[WARN] Failed sync for {info.path}: {detail}")

    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
