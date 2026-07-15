"""Runtime orchestration for codex-session-sync."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from codex_sync_api import finalize_and_close, ingest_transcript, send_heartbeat, upsert_session
from codex_sync_git import build_project_context
from codex_sync_state import (
    get_checkpoint,
    get_state_entry,
    iter_nonterminal_paths,
    load_state,
    save_state,
    should_heartbeat,
    should_sync,
    update_state_entry,
)
from codex_sync_transcripts import (
    AicoProcessOwner,
    OpenTranscriptSnapshot,
    discover_open_transcripts,
    has_live_codex_process,
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
    parent_session_id: str | None
    agent_nickname: str | None
    agent_path: str | None
    is_open: bool
    process_owner: AicoProcessOwner | None
    ownership_ambiguous: bool


def run_sync(
    args: argparse.Namespace,
    *,
    api_url: str,
    client_id: str,
    source_path: str,
    log_fn: LogFn,
) -> int:
    state = load_state()
    open_snapshot = discover_open_transcripts()
    infos = _transcript_infos(args, state, open_snapshot, log_fn)
    live_transcript_paths, saw_live_codex_process = _live_session_context(
        args,
        open_snapshot,
        log_fn,
    )
    _sync_infos(
        args=args,
        state=state,
        infos=infos,
        api_url=api_url,
        client_id=client_id,
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
    source_path: str,
    close_session: bool,
    ingest_required: bool,
    heartbeat_required: bool,
    log_fn: LogFn,
    verbose: bool,
) -> tuple[bool, str, int | None]:
    project_data = build_project_context(info.cwd)
    if not isinstance(project_data, dict):
        return False, f"skip unmapped/unregistered cwd={info.cwd}", None
    project: dict[str, object] = project_data

    mapping_state, mapping_error = _project_mapping_state(info, project)
    if mapping_error:
        return False, mapping_error, None
    meta = _session_meta(info, project, mapping_state)
    identity_fingerprint = _identity_fingerprint(info, project, meta)
    kw = _sync_keywords(api_url, client_id, source_path)

    ok, err, status, project = _ensure_session_upserted(
        info,
        state,
        project,
        meta,
        identity_fingerprint,
        kw,
    )
    if not ok:
        return False, err, status

    entry = get_state_entry(info.path, state) or {}
    same_transcript_identity = entry.get("session_id") == info.session_id
    checkpoint = (
        get_checkpoint(info.path, state)
        if same_transcript_identity
        else None
    )
    next_checkpoint = checkpoint
    detail = str(entry.get("detail") or "unchanged")
    if ingest_required:
        ok, next_checkpoint, detail, err, status = ingest_transcript(
            info.session_id,
            info.path,
            checkpoint,
            **kw,
        )
        if not ok:
            return False, err, status

    heartbeat_at: str | None = None
    if heartbeat_required and not close_session:
        ok, err, status = send_heartbeat(info.session_id, info.cwd, project, meta, **kw)
        if not ok:
            return False, err, status
        heartbeat_at = datetime.now(UTC).isoformat()
        if not ingest_required:
            detail = "heartbeat"

    if close_session:
        ok, err, status = finalize_and_close(info.session_id, project, True, **kw)
        if not ok:
            return False, err, status

    sync_status = "terminal" if close_session else ("active" if info.is_open else "synced")
    update_state_entry(
        state,
        info.path,
        info.session_id,
        info.mtime,
        info.size,
        sync_status,
        detail,
        checkpoint=next_checkpoint,
        preserve_checkpoint=same_transcript_identity,
        identity_fingerprint=identity_fingerprint,
        heartbeat_at=heartbeat_at,
    )
    if verbose:
        log_fn(
            f"[INFO] Synced session={info.session_id} project={project['project_id']} "
            f"transcript={info.path} ingest={ingest_required} heartbeat={heartbeat_required} "
            f"close={close_session}"
        )
    return True, "ok", None


def _project_mapping_state(
    info: TranscriptInfoLike,
    project: dict[str, object],
) -> tuple[str, str]:
    if info.ownership_ambiguous:
        return "ambiguous", f"conflict ambiguous AICO ownership transcript={info.path}"
    owner = info.process_owner
    if owner is None:
        return "git_only", ""

    project_id = str(project["project_id"])
    aliases = {
        alias
        for alias in project.get("project_aliases", [])
        if isinstance(alias, str) and alias
    }
    if not owner.aico_project_id:
        return (
            "unmapped",
            f"conflict AICO owner has no project mapping transcript={info.path}",
        )
    if owner.aico_project_id not in {project_id, *aliases}:
        return (
            "mismatch",
            "conflict AICO/Git project mismatch "
            f"aico={owner.aico_project_id} git={project_id} transcript={info.path}",
        )
    return "matched", ""


def _session_meta(
    info: TranscriptInfoLike,
    project: dict[str, object],
    project_mapping_state: str,
) -> dict[str, object]:
    owner = info.process_owner
    harness = owner.harness if owner is not None else "codex"
    return {
        "transcript_path": str(info.path),
        "repo_root": project["repo_root"],
        "cwd": str(info.cwd),
        "host": os.uname().nodename,
        "external_identity": {
            "harness": harness,
            "launcher": "aico" if owner is not None else "direct",
            "display_identity": info.agent_nickname or harness,
            "runtime_session_id": info.session_id,
            "agent_path": info.agent_path or "/root",
            "aico_session_id": owner.aico_session_id if owner is not None else None,
            "aico_widget_id": owner.aico_widget_id if owner is not None else None,
            "aico_project_id": owner.aico_project_id if owner is not None else None,
            "project_mapping_state": project_mapping_state,
        },
    }


def _identity_fingerprint(
    info: TranscriptInfoLike,
    project: dict[str, object],
    meta: dict[str, object],
) -> str:
    canonical = {
        "session_id": info.session_id,
        "parent_session_id": info.parent_session_id,
        "project_id": project["project_id"],
        "external_identity": meta["external_identity"],
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sync_keywords(api_url: str, client_id: str, source_path: str) -> dict[str, str]:
    return {
        "api_url": api_url,
        "client_id": client_id,
        "source_path": source_path,
    }


def _ensure_session_upserted(
    info: TranscriptInfoLike,
    state: dict[str, object],
    project: dict[str, object],
    meta: dict[str, object],
    identity_fingerprint: str,
    kw: dict[str, str],
) -> tuple[bool, str, int | None, dict[str, object]]:
    entry = get_state_entry(info.path, state)
    if not _should_upsert(entry, info.session_id, identity_fingerprint, is_open=info.is_open):
        return True, "", None, project
    return _upsert_with_project_aliases(info=info, project=project, meta=meta, kw=kw)


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


def _should_upsert(
    entry: dict[str, object] | None,
    session_id: str,
    identity_fingerprint: str,
    *,
    is_open: bool,
) -> bool:
    if entry is None:
        return True
    if (
        not is_open
        and entry.get("session_id") == session_id
        and entry.get("identity_fingerprint")
        and entry.get("status") in {"active", "synced", "terminal"}
    ):
        # A closed process no longer exposes its AICO environment.  Preserve the
        # richer identity previously recorded while it was live instead of
        # replacing it with a synthetic direct-launch identity during closeout.
        return False
    return not (
        entry.get("session_id") == session_id
        and entry.get("identity_fingerprint") == identity_fingerprint
        and entry.get("status") in {"active", "synced", "terminal"}
    )


def _upsert_with_project_aliases(
    *,
    info: TranscriptInfoLike,
    project: dict[str, object],
    meta: dict[str, object],
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
            parent_session_id=info.parent_session_id,
            provider_metadata=meta,
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


def _transcript_infos(
    args: argparse.Namespace,
    state: dict[str, object],
    open_snapshot: OpenTranscriptSnapshot,
    log_fn: LogFn,
) -> list[TranscriptInfoLike]:
    if args.transcript is not None:
        info = read_transcript_info(
            args.transcript,
            log_fn=log_fn,
            open_snapshot=open_snapshot,
        )
        infos: list[TranscriptInfoLike] = [info] if info is not None else []
    else:
        recent = iter_recent_transcripts(
            args.recent_hours,
            log_fn=log_fn,
            open_snapshot=open_snapshot,
        )
        by_path: dict[Path, TranscriptInfoLike] = {
            _resolve_transcript_path(info.path): info for info in recent
        }
        candidates = set(open_snapshot.paths)
        if args.close_inactive:
            candidates.update(iter_nonterminal_paths(state))
        for path in sorted(candidates):
            resolved = _resolve_transcript_path(path)
            if resolved in by_path:
                continue
            info = read_transcript_info(path, log_fn=log_fn, open_snapshot=open_snapshot)
            if info is not None:
                by_path[resolved] = info
        infos = list(by_path.values())

    if args.cwd is not None:
        target_cwd = args.cwd.expanduser().resolve()
        infos = [info for info in infos if info.cwd.expanduser().resolve() == target_cwd]
    return _parents_before_children(infos)


def _parents_before_children(infos: list[TranscriptInfoLike]) -> list[TranscriptInfoLike]:
    by_session = {info.session_id: info for info in infos}
    depths: dict[str, int] = {}

    def depth(session_id: str, trail: frozenset[str] = frozenset()) -> int:
        if session_id in depths:
            return depths[session_id]
        if session_id in trail:
            return len(infos) + 1
        info = by_session[session_id]
        parent_id = info.parent_session_id
        value = 0
        if parent_id in by_session:
            value = 1 + depth(parent_id, trail | {session_id})
        depths[session_id] = value
        return value

    return sorted(
        infos,
        key=lambda info: (depth(info.session_id), info.mtime, info.session_id),
    )


def _live_session_context(
    args: argparse.Namespace,
    open_snapshot: OpenTranscriptSnapshot,
    log_fn: LogFn,
) -> tuple[set[Path], bool]:
    live_transcript_paths = set(open_snapshot.paths)
    if not args.close_inactive:
        return live_transcript_paths, False
    saw_live_codex_process = has_live_codex_process()
    if saw_live_codex_process and not live_transcript_paths:
        log_fn(
            "[WARN] Live Codex process found but no open transcript files detected; "
            "skipping inactive session close pass"
        )
    return live_transcript_paths, saw_live_codex_process


def _sync_infos(
    *,
    args: argparse.Namespace,
    state: dict[str, object],
    infos: list[TranscriptInfoLike],
    api_url: str,
    client_id: str,
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
        ingest_required = should_sync(
            info.path,
            info.mtime,
            info.size,
            state,
            args.force,
        )
        close_required = close_session and should_sync(
            info.path,
            info.mtime,
            info.size,
            state,
            args.force,
            close_session=True,
        )
        heartbeat_required = (
            info.is_open
            and not close_session
            and should_heartbeat(info.path, state, force=args.force)
        )
        if not ingest_required and not close_required and not heartbeat_required:
            continue
        ok, detail, status = sync_transcript(
            info=info,
            state=state,
            api_url=api_url,
            client_id=client_id,
            source_path=source_path,
            close_session=close_required,
            ingest_required=ingest_required,
            heartbeat_required=heartbeat_required,
            log_fn=log_fn,
            verbose=args.verbose,
        )
        if ok:
            continue
        if detail.startswith("skip "):
            _record_skipped(state, info, detail, log_fn)
        else:
            _record_sync_error(state, info, detail, status, log_fn)


def _record_skipped(
    state: dict[str, object],
    info: TranscriptInfoLike,
    detail: str,
    log_fn: LogFn,
) -> None:
    update_state_entry(
        state,
        info.path,
        info.session_id,
        info.mtime,
        info.size,
        "skipped",
        detail,
    )
    log_fn(f"[WARN] {detail} transcript={info.path}")


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
