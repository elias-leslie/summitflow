"""Transcript discovery and parsing for codex-session-sync."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

TRANSCRIPTS_ROOT = Path.home() / ".codex" / "sessions"
DEFAULT_MODEL = "gpt-5.4"
TRANSCRIPT_SCAN_LINES = 100


@dataclass(frozen=True)
class TranscriptInfo:
    path: Path
    session_id: str
    cwd: Path
    model: str
    mtime: float
    size: int


def _extract_transcript_fields(path: Path) -> tuple[str, str, str]:
    """Read up to TRANSCRIPT_SCAN_LINES lines and extract session_id, cwd, model."""
    session_id = cwd = model = ""
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= TRANSCRIPT_SCAN_LINES:
                break
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = obj.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            obj_type = obj.get("type")
            if obj_type == "session_meta":
                session_id = str(payload.get("id") or session_id)
                cwd = str(payload.get("cwd") or cwd)
            elif obj_type == "turn_context" and not model:
                model = str(payload.get("model") or model)
            if session_id and cwd and model:
                break
    return session_id, cwd, model


def read_transcript_info(path: Path, log_fn: object = None) -> TranscriptInfo | None:
    """Parse a JSONL transcript file and return metadata from its header lines."""
    try:
        session_id, cwd, model = _extract_transcript_fields(path)
    except OSError as exc:
        if log_fn:
            log_fn(f"[WARN] Failed to read transcript {path}: {exc}")
        return None
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


def iter_recent_transcripts(recent_hours: int, log_fn: object = None) -> list[TranscriptInfo]:
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
        info = read_transcript_info(path, log_fn=log_fn)
        if info is not None:
            transcripts.append(info)
    transcripts.sort(key=lambda item: item.mtime)
    return transcripts
