"""State management for codex-session-sync: load, save, update, and check."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

STATE_PATH = Path.home() / ".local" / "state" / "codex-session-sync" / "state.json"


def load_state() -> dict[str, object]:
    if not STATE_PATH.exists():
        return {"transcripts": {}}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"transcripts": {}}
    except json.JSONDecodeError:
        return {"transcripts": {}}


def save_state(state: dict[str, object]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def update_state_entry(
    state: dict[str, object],
    path: Path,
    session_id: str,
    mtime: float,
    size: int,
    status: str,
    detail: str,
    checkpoint: str | None = None,
) -> None:
    transcripts = state.setdefault("transcripts", {})
    if not isinstance(transcripts, dict):
        state["transcripts"] = {}
        transcripts = state["transcripts"]  # type: ignore[assignment]
    transcripts[str(path)] = {  # type: ignore[index]
        "session_id": session_id,
        "mtime": mtime,
        "size": size,
        "status": status,
        "detail": detail,
        "checkpoint": checkpoint,
        "updated_at": datetime.now(UTC).isoformat(),
    }


def should_sync(path: Path, mtime: float, size: int, state: dict[str, object], force: bool) -> bool:
    if force:
        return True
    entries = state.get("transcripts") or {}
    if not isinstance(entries, dict):
        return True
    entry = entries.get(str(path))
    if not isinstance(entry, dict):
        return True
    return entry.get("mtime") != mtime or entry.get("size") != size


def get_checkpoint(path: Path, state: dict[str, object]) -> str | None:
    entries = state.get("transcripts") or {}
    if not isinstance(entries, dict):
        return None
    entry = entries.get(str(path))
    if not isinstance(entry, dict):
        return None
    return entry.get("checkpoint")  # type: ignore[return-value]
