"""Runtime orchestration for codex-session-sync."""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from codex_sync_api import finalize_and_close, ingest_transcript, send_heartbeat, upsert_session
from codex_sync_git import build_project_context
from codex_sync_state import (
    get_checkpoint,
    get_state_entry,
    load_state,
    save_state,
    should_sync,
    update_state_entry,
)
from codex_sync_transcripts import (
    has_live_codex_process,
    iter_open_transcript_paths,
    iter_recent_transcripts,
    read_transcript_info,
)

LogFn = Callable[[str], None]

PERMANENT_HTTP_STATUSES = {400, 404, 410, 422}


class TranscriptInfoLike(Protocol):
    session_id: str
    path: Path
    cwd: Path
    model: str
    mtime: float
    size: int


def run_sync(
    args: argparse.Namespace,
    *,
    api_url: str,
    client_id: str,
    client_secret: str,
    source_path: str,
    log_fn: LogFn,
) -> int:
    state = load_state()
    infos = _transcript_infos(args, log_fn)
    live_transcript_paths, saw_live_codex_process = _live_session_context(args, log_fn)
    _sync_infos(
        args=args,
        state=state,
        infos=infos,
        api_url=api_url,
        client_id=client_id,
        client_secret=client_secret,
        source_path=source_path,
        log_fn=log_fn,
        live_transcript_paths=live_transcript_paths,
        saw_live_codex_process=saw_live_codex_process,
    )
    save_state(state)
    return 0


def sync_transcript(
    info: TranscriptInfoLike,
    state: dict[str, object],
    api_url: str,
    client_id: str,
    client_secret: str,
    source_path: str,
    close_session: bool,
    log_fn: LogFn,
    verbose: bool,
) -> tuple[bool, str, int | None]:
    project_data = build_project_context(info.cwd)
    if not isinstance(project_data, dict):
        return False, f"skip non-git cwd={info.cwd}", None
    project: dict[str, object] = project_data
    meta = _session_meta(info, project)
    kw = _sync_keywords(api_url, client_id, client_secret, source_path)

    ok, err, status, project = _ensure_session_upserted(info, state, project, kw)
    if not ok:
        return False, err, status
    ok, next_cp, detail, err, status = _ingest_and_heartbeat(info, state, project, meta, kw)
    if not ok:
        return False, err, status
    ok, sync_status, err, status = _maybe_close_session(info, project, close_session, kw)
    if not ok:
        return False, err, status

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
        log_fn(f"[INFO] Synced session={info.session_id} project={project['project_id']} "
               f"transcript={info.path} close={close_session}")
    return True, "ok", None


def _session_meta(info: TranscriptInfoLike, project: dict[str, object]) -> dict[str, object]:
    return {
        "transcript_path": str(info.path),
        "repo_root": project["repo_root"],
        "cwd": str(info.cwd),
        "host": os.uname().nodename,
    }


def _sync_keywords(
    api_url: str,
    client_id: str,
    client_secret: str,
    source_path: str,
) -> dict[str, str]:
    return {
        "api_url": api_url,
        "client_id": client_id,
        "client_secret": client_secret,
        "source_path": source_path,
    }


def _ensure_session_upserted(
    info: TranscriptInfoLike,
    state: dict[str, object],
    project: dict[str, object],
    kw: dict[str, str],
) -> tuple[bool, str, int | None, dict[str, object]]:
    entry = get_state_entry(info.path, state)
    if not _should_upsert(entry, info.session_id):
        return True, "", None, project
    return _upsert_with_project_aliases(info=info, project=project, kw=kw)


def _ingest_and_heartbeat(
    info: TranscriptInfoLike,
    state: dict[str, object],
    project: dict[str, object],
    meta: dict[str, object],
    kw: dict[str, str],
) -> tuple[bool, object, str, str, int | None]:
    checkpoint = get_checkpoint(info.path, state)
    ok, next_cp, detail, err, status = ingest_transcript(
        info.session_id,
        info.path,
        checkpoint,
        **kw,
    )
    if not ok:
        return False, next_cp, detail, err, status
    ok, err, status = send_heartbeat(info.session_id, info.cwd, project, meta, **kw)
    return ok, next_cp, detail, err, status


def _maybe_close_session(
    info: TranscriptInfoLike,
    project: dict[str, object],
    close_session: bool,
    kw: dict[str, str],
) -> tuple[bool, str, str, int | None]:
    if not close_session:
        return True, "active", "", None
    ok, err, status = finalize_and_close(info.session_id, project, close_session, **kw)
    return ok, "terminal", err, status


def _resolve_transcript_path(path: Path) -> Path:
    try:
        return path.expanduser().resolve(strict=False)
    except OSError:
        return path.expanduser()


def _close_inactive_session(
    info: TranscriptInfoLike,
    *,
    close_all: bool,
    close_inactive: bool,
    live_transcript_paths: set[Path],
    saw_live_codex_process: bool,
) -> bool:
    if close_all:
        return True
    if not close_inactive:
        return False
    if saw_live_codex_process and not live_transcript_paths:
        return False
    return _resolve_transcript_path(info.path) not in live_transcript_paths


def _should_upsert(entry: dict[str, object] | None, session_id: str) -> bool:
    if entry is None:
        return True
    return not (
        entry.get("session_id") == session_id
        and entry.get("status") in {"active", "synced", "terminal"}
    )


def _upsert_with_project_aliases(
    *,
    info: TranscriptInfoLike,
    project: dict[str, object],
    kw: dict[str, str],
) -> tuple[bool, str, int | None, dict[str, object]]:
    candidates = [project, *_project_aliases(project)]
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


def _project_aliases(project: dict[str, object]) -> list[dict[str, object]]:
    aliases = project.get("project_aliases")
    if not isinstance(aliases, list):
        return []
    candidates: list[dict[str, object]] = []
    for alias in aliases:
        if not isinstance(alias, str) or not alias:
            continue
        alias_project = dict(project)
        alias_project["project_id"] = alias
        candidates.append(alias_project)
    return candidates


def _transcript_infos(args: argparse.Namespace, log_fn: LogFn) -> list[TranscriptInfoLike]:
    if args.transcript is not None:
        info = read_transcript_info(args.transcript, log_fn=log_fn)
        infos: list[TranscriptInfoLike] = [info] if info is not None else []
    else:
        infos = iter_recent_transcripts(args.recent_hours, log_fn=log_fn)
    if args.cwd is None:
        return infos
    target_cwd = args.cwd.expanduser().resolve()
    return [info for info in infos if info.cwd.expanduser().resolve() == target_cwd]


def _live_session_context(args: argparse.Namespace, log_fn: LogFn) -> tuple[set[Path], bool]:
    if not args.close_inactive:
        return set(), False
    live_transcript_paths = iter_open_transcript_paths()
    saw_live_codex_process = has_live_codex_process()
    if saw_live_codex_process and not live_transcript_paths:
        log_fn("[WARN] Live Codex process found but no open transcript files detected; "
               "skipping inactive session close pass")
    return live_transcript_paths, saw_live_codex_process


def _sync_infos(
    *,
    args: argparse.Namespace,
    state: dict[str, object],
    infos: list[TranscriptInfoLike],
    api_url: str,
    client_id: str,
    client_secret: str,
    source_path: str,
    log_fn: LogFn,
    live_transcript_paths: set[Path],
    saw_live_codex_process: bool,
) -> None:
    for info in infos:
        close_session = _close_inactive_session(
            info,
            close_all=args.close,
            close_inactive=args.close_inactive,
            live_transcript_paths=live_transcript_paths,
            saw_live_codex_process=saw_live_codex_process,
        )
        if not _sync_required(info, state, args.force, close_session):
            continue
        ok, detail, status = sync_transcript(
            info=info, state=state, api_url=api_url,
            client_id=client_id, client_secret=client_secret,
            source_path=source_path, close_session=close_session,
            log_fn=log_fn, verbose=args.verbose,
        )
        if not ok:
            _record_sync_error(state, info, detail, status, log_fn)


def _sync_required(
    info: TranscriptInfoLike,
    state: dict[str, object],
    force: bool,
    close_session: bool,
) -> bool:
    return should_sync(
        info.path,
        info.mtime,
        info.size,
        state,
        force,
        close_session=close_session,
    )


def _record_sync_error(
    state: dict[str, object],
    info: TranscriptInfoLike,
    detail: str,
    status: int | None,
    log_fn: LogFn,
) -> None:
    update_state_entry(
        state,
        info.path,
        info.session_id,
        info.mtime,
        info.size,
        "permanent_error" if status in PERMANENT_HTTP_STATUSES else "error",
        detail,
    )
    log_fn(f"[WARN] Failed sync for {info.path}: {detail}")
