"""Oversized progress stays exact in export and bounded in active continuity."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from unittest.mock import patch

import pytest

from app.services.task_continuity import (
    MAX_PROGRESS_ENTRY_BYTES,
    build_continuity,
    format_continuity_lines,
)

TASK_ID = "fixture-task-id"


def _continuity(entries: list[str]) -> dict:
    return build_continuity(
        task={"id": TASK_ID},
        spirit=None,
        subtasks=[],
        blockers=[{"id": "task-review", "status": "pending", "title": "Review required"}],
        progress_log=entries,
        summary=None,
    )


def _omitted_bytes(excerpt: str) -> int:
    match = re.search(r"\n\[omitted (\d+) bytes;.*?\]\n", excerpt)
    assert match is not None
    retained = excerpt[:match.start()] + excerpt[match.end():]
    return int(match[1]) + len(retained.encode("utf-8"))


@pytest.mark.parametrize("byte_count", [MAX_PROGRESS_ENTRY_BYTES - 1, MAX_PROGRESS_ENTRY_BYTES])
def test_entries_at_boundary_keep_existing_text(byte_count: int) -> None:
    entry = "x" * byte_count
    assert _continuity([entry])["recent_progress"] == [entry]


def test_entry_one_byte_over_boundary_has_exact_omission_count() -> None:
    entry = "x" * (MAX_PROGRESS_ENTRY_BYTES + 1)
    excerpt = _continuity([entry])["recent_progress"][0]
    assert len(excerpt.encode("utf-8")) <= MAX_PROGRESS_ENTRY_BYTES
    assert _omitted_bytes(excerpt) == len(entry.encode("utf-8"))


def test_multibyte_excerpt_is_valid_utf8_and_preserves_both_ends() -> None:
    entry = "[2026-10-03 09:00:00] " + "界🌍é" * 1200 + " Decision: await review."
    excerpt = _continuity([entry])["recent_progress"][0]
    assert excerpt.startswith("[2026-10-03 09:00:00] ")
    assert excerpt.endswith(" Decision: await review.")
    assert len(excerpt.encode("utf-8")) <= MAX_PROGRESS_ENTRY_BYTES
    assert "�" not in excerpt
    assert _omitted_bytes(excerpt) == len(entry.encode("utf-8"))


def test_source_digest_is_exact_stable_and_precedes_display_normalization() -> None:
    entry = "  [2026-10-03 09:00:00] " + "detail " * 800 + " Decision: wait.  "
    original: list[str] = [entry]
    excerpt = _continuity(original)["recent_progress"][0]
    assert original == [entry]
    assert excerpt == _continuity(original)["recent_progress"][0]
    assert f"source={TASK_ID}; sha256={hashlib.sha256(entry.encode()).hexdigest()}" in excerpt
    assert f"bytes={len(entry.encode())}" in excerpt
    assert f"detail=st export {TASK_ID}" in excerpt
    assert _omitted_bytes(excerpt) == len(entry.encode())
    assert excerpt != _continuity([entry.strip()])["recent_progress"][0]


def test_oversized_whitespace_records_omissions_without_duplicating_content() -> None:
    entry = " " * MAX_PROGRESS_ENTRY_BYTES + "Current decision: wait."
    excerpt = _continuity([entry])["recent_progress"][0]
    assert len(excerpt.encode()) <= MAX_PROGRESS_ENTRY_BYTES
    assert excerpt.count("Current decision: wait.") == 1
    assert hashlib.sha256(entry.encode()).hexdigest() in excerpt
    assert _omitted_bytes(excerpt) == len(entry.encode())


def test_11037_byte_message_pattern_remains_exact_in_export_and_small_in_continuity() -> None:
    from app.api.tasks.workflow_export import _build_progress_log

    timestamp = datetime(2026, 10, 3, 9, 0, 0)
    prefix = f"[{timestamp:%Y-%m-%d %H:%M:%S}] "
    decision = " Current decision: retain evidence; blocker: independent review."
    # Match the observed size, line count and encoding without production text.
    diagnostic = "diagnostic 🌍\n" * 170
    message = diagnostic + "x" * (11037 - len((diagnostic + decision).encode())) + decision
    entry = prefix + message
    assert len(message.encode()) == 11037
    assert len(message.splitlines()) == 171
    assert len(entry.encode()) == 11059
    events = [{"timestamp": timestamp, "message": message}]
    with patch("app.api.tasks.workflow_export.get_events_by_trace", return_value=events):
        exact_export = _build_progress_log(TASK_ID)
        continuity = _continuity(exact_export)
        assert _build_progress_log(TASK_ID) == [entry]

    assert events[0]["message"] == message
    assert exact_export == [entry]
    excerpt = continuity["recent_progress"][0]
    assert excerpt.startswith(prefix)
    assert excerpt.endswith(decision)
    assert _omitted_bytes(excerpt) == 11059
    assert hashlib.sha256(exact_export[0].encode()).hexdigest() in excerpt
    assert "task-review|pending|Review required" in continuity["blockers"]
    assert len("\n".join(format_continuity_lines(continuity)).encode()) < 1800


def test_recent_selection_deduplication_and_three_entry_output_bound() -> None:
    entries = ["Old decision", *(f"[{index}] " + "x" * 11037 for index in range(3))]
    entries.extend([entries[-1], "  "])
    continuity = _continuity(entries)
    recent = continuity["recent_progress"]
    assert len(recent) == 3
    assert all(item.startswith(f"[{index}] ") for index, item in enumerate(recent))
    assert sum(len(item.encode()) for item in recent) <= 3 * MAX_PROGRESS_ENTRY_BYTES
    assert len("\n".join(format_continuity_lines(continuity)).encode()) < 5000
