from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_LIB = Path(__file__).resolve().parents[3] / "scripts" / "lib"
if str(SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_LIB))

import codex_sync_state


def _state_for(path: Path, *, status: str, mtime: float = 10.0, size: int = 200) -> dict[str, object]:
    return {
        "transcripts": {
            str(path): {
                "session_id": "sess-1",
                "mtime": mtime,
                "size": size,
                "status": status,
                "detail": "appended=0 skipped=0",
                "updated_at": "2026-04-16T00:00:00+00:00",
            }
        }
    }


def test_should_sync_skips_unchanged_active_entry_without_close() -> None:
    path = Path("/tmp/transcript.jsonl")
    state = _state_for(path, status="active")

    assert not codex_sync_state.should_sync(path, 10.0, 200, state, force=False)


def test_should_sync_allows_close_for_unchanged_active_entry() -> None:
    path = Path("/tmp/transcript.jsonl")
    state = _state_for(path, status="active")

    assert codex_sync_state.should_sync(
        path,
        10.0,
        200,
        state,
        force=False,
        close_session=True,
    )


def test_should_sync_still_skips_terminal_entry_during_close() -> None:
    path = Path("/tmp/transcript.jsonl")
    state = _state_for(path, status="terminal")

    assert not codex_sync_state.should_sync(
        path,
        10.0,
        200,
        state,
        force=False,
        close_session=True,
    )
