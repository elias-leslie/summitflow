"""State management for codex-session-sync: load, save, update, and check."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

STATE_PATH = Path.home() / ".local" / "state" / "codex-session-sync" / "state.json"
ERROR_RETRY_SECONDS = 300


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


def get_state_entry(path: Path, state: dict[str, object]) -> dict[str, object] | None:
    entries = state.get("transcripts") or {}
    if not isinstance(entries, dict):
        return None
    entry = entries.get(str(path))
    return entry if isinstance(entry, dict) else None


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


def should_sync(
    path: Path,
    mtime: float,
    size: int,
    state: dict[str, object],
    force: bool,
    *,
    close_session: bool = False,
) -> bool:
    if force:
        return True
    entry = get_state_entry(path, state)
    if entry is None:
        return True
    if close_session:
        return entry.get("status") != "terminal"
    if entry.get("status") == "terminal":
        return False
    if _entry_is_permanent_error(entry):
        return False
    if entry.get("mtime") != mtime or entry.get("size") != size:
        return True
    if entry.get("status") != "error":
        return False
    return _error_retry_due(entry)


def get_checkpoint(path: Path, state: dict[str, object]) -> str | None:
    entry = get_state_entry(path, state)
    if entry is None:
        return None
    return entry.get("checkpoint")  # type: ignore[return-value]


def _entry_is_permanent_error(entry: dict[str, object]) -> bool:
    status = str(entry.get("status") or "")
    if status == "permanent_error":
        return True
    if status != "error":
        return False
    detail = str(entry.get("detail") or "")
    return any(token in detail for token in ("status=400", "status=404", "status=410", "status=422"))


def _error_retry_due(entry: dict[str, object]) -> bool:
    updated_at = entry.get("updated_at")
    if not isinstance(updated_at, str) or not updated_at:
        return True
    try:
        updated = datetime.fromisoformat(updated_at)
    except ValueError:
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return (datetime.now(UTC) - updated).total_seconds() >= ERROR_RETRY_SECONDS
