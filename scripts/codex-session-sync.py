#!/usr/bin/env python3
"""Sync Codex transcript analysis into Agent Hub without waiting for process exit."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# Ensure scripts/lib is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from codex_sync_api import (  # noqa: E402
    finalize_and_close,
    ingest_transcript,
    send_heartbeat,
    upsert_session,
)
from codex_sync_credentials import load_env_credentials  # noqa: E402
from codex_sync_git import build_project_context  # noqa: E402
from codex_sync_state import (  # noqa: E402
    get_state_entry,
    get_checkpoint,
    load_state,
    save_state,
    should_sync,
    update_state_entry,
)
from codex_sync_transcripts import (  # noqa: E402
    TranscriptInfo,
    iter_recent_transcripts,
    read_transcript_info,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_API = os.environ.get("AGENT_HUB_API", "http://localhost:8003/api")
LOG_PATH = Path.home() / ".codex" / "session-integrations" / "codex-session-sync.log"
_SOURCE_PATH = str(Path(__file__))
_PERMANENT_HTTP_STATUSES = {400, 404, 410, 422}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat()
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")


# ---------------------------------------------------------------------------
# Sync orchestration
# ---------------------------------------------------------------------------


def sync_transcript(
    info: TranscriptInfo,
    state: dict[str, object],
    api_url: str,
    client_id: str,
    client_secret: str,
    close_session: bool,
    verbose: bool,
) -> tuple[bool, str, int | None]:
    project = build_project_context(info.cwd)
    if project is None:
        return False, f"skip non-git cwd={info.cwd}", None

    meta: dict[str, object] = {
        "transcript_path": str(info.path),
        "repo_root": project["repo_root"],
        "worktree_path": str(info.cwd),
        "host": os.uname().nodename,
    }
    kw = dict(api_url=api_url, client_id=client_id, client_secret=client_secret,
               source_path=_SOURCE_PATH)
    entry = get_state_entry(info.path, state)

    if _should_upsert(entry, info.session_id):
        ok, err, status, project = _upsert_with_project_aliases(
            info=info,
            project=project,
            kw=kw,
        )
        if not ok:
            return False, err, status

    checkpoint = get_checkpoint(info.path, state)
    ok, next_cp, detail, err, status = ingest_transcript(
        info.session_id,
        info.path,
        checkpoint,
        **kw,
    )
    if not ok:
        return False, err, status

    ok, err, status = send_heartbeat(info.session_id, info.cwd, project, meta, **kw)
    if not ok:
        return False, err, status

    sync_status = "active"
    if close_session:
        ok, err, status = finalize_and_close(info.session_id, project, close_session, **kw)
        if not ok:
            return False, err, status
        sync_status = "terminal"

    update_state_entry(
        state,
        info.path,
        info.session_id,
        info.mtime,
        info.size,
        sync_status,
        detail,
        checkpoint=next_cp,
    )

    if verbose:
        log(f"[INFO] Synced session={info.session_id} project={project['project_id']} "
            f"transcript={info.path} close={close_session}")
    return True, "ok", None


def _should_upsert(entry: dict[str, object] | None, session_id: str) -> bool:
    if entry is None:
        return True
    return not (
        entry.get("session_id") == session_id
        and entry.get("status") in {"active", "synced", "terminal"}
    )


def _upsert_with_project_aliases(
    *,
    info: TranscriptInfo,
    project: dict[str, object],
    kw: dict[str, object],
) -> tuple[bool, str, int | None, dict[str, object]]:
    candidates = [project]
    for alias in project.get("project_aliases", []):
        if not isinstance(alias, str) or not alias:
            continue
        alias_project = dict(project)
        alias_project["project_id"] = alias
        candidates.append(alias_project)

    last_err = ""
    last_status: int | None = None
    for candidate in candidates:
        ok, err, status = upsert_session(
            info.session_id,
            candidate,
            info.model,
            info.cwd,
            info.path,
            **kw,
        )
        if ok:
            return True, "", status, candidate
        last_err = err
        last_status = status
        if status != 400 or "Unknown project_id" not in err:
            break
    return False, last_err, last_status, project


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", action="store_true", help="Scan recent Codex transcripts")
    parser.add_argument("--transcript", type=Path, help="Sync a specific transcript path")
    parser.add_argument("--recent-hours", type=int, default=24, help="Recent hours to scan")
    parser.add_argument("--cwd", type=Path, help="Only scan transcripts from this working directory")
    parser.add_argument("--close", action="store_true",
                        help="Close the Agent Hub session after analysis")
    parser.add_argument("--force", action="store_true",
                        help="Sync even if transcript state is unchanged")
    parser.add_argument("--verbose", action="store_true",
                        help="Write success entries to the sync log")
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
        info = read_transcript_info(args.transcript, log_fn=log)
        infos: list[TranscriptInfo] = [info] if info is not None else []
    else:
        infos = iter_recent_transcripts(args.recent_hours, log_fn=log)
    if args.cwd is not None:
        target_cwd = args.cwd.expanduser().resolve()
        infos = [info for info in infos if info.cwd.expanduser().resolve() == target_cwd]

    for info in infos:
        if not should_sync(info.path, info.mtime, info.size, state, args.force):
            continue
        ok, detail, status = sync_transcript(
            info=info, state=state, api_url=DEFAULT_API,
            client_id=client_id, client_secret=client_secret,
            close_session=args.close, verbose=args.verbose,
        )
        if not ok:
            update_state_entry(
                state,
                info.path,
                info.session_id,
                info.mtime,
                info.size,
                "permanent_error" if status in _PERMANENT_HTTP_STATUSES else "error",
                detail,
            )
            log(f"[WARN] Failed sync for {info.path}: {detail}")

    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
