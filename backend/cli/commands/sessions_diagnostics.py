"""Session diagnostic (error/repeat analysis) helpers for the sessions CLI commands."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

_ERROR_TEXT_MARKERS = (
    "traceback",
    "error",
    "exception",
    "failed",
    "test:fail",
    "valueerror",
    "typeerror",
    "use 'st check",
)


def event_text(event: dict[str, Any]) -> str:
    """Extract concatenated text content from an event dict."""
    parts: list[str] = []
    for key in ("content", "tool_output", "message", "error"):
        value = event.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            parts.append(value)
        else:
            try:
                parts.append(json.dumps(value, default=str, sort_keys=True))
            except TypeError:
                parts.append(str(value))
    return "\n".join(parts)


def event_signature(event: dict[str, Any]) -> str:
    """Return a truncated normalized text signature for deduplication."""
    text = event_text(event)
    if not text:
        return "-"
    normalized = " ".join(text.replace("\n", " ").split())
    return normalized if len(normalized) <= 180 else normalized[:177] + "..."


def is_error_like(event: dict[str, Any], signature: str) -> bool:
    """Return True if the event looks like an error."""
    if str(event.get("event_type") or "").lower() == "error":
        return True
    lower = signature.lower()
    return any(marker in lower for marker in _ERROR_TEXT_MARKERS)


def diagnostic_rows(
    events: list[dict[str, Any]],
) -> tuple[
    list[tuple[str, int, dict[str, Any]]],
    list[tuple[str, int, dict[str, Any]]],
]:
    """Return (error_rows, repeat_rows) tuples from a list of events."""
    signatures: list[str] = []
    first_by_signature: dict[str, dict[str, Any]] = {}
    for event in events:
        sig = event_signature(event)
        if sig == "-":
            continue
        signatures.append(sig)
        first_by_signature.setdefault(sig, event)

    counts = Counter(signatures)
    error_rows = [
        (sig, count, first_by_signature[sig])
        for sig, count in counts.items()
        if is_error_like(first_by_signature[sig], sig)
    ]
    error_rows.sort(key=lambda row: (-row[1], row[0]))
    repeat_rows = [
        (sig, count, first_by_signature[sig])
        for sig, count in counts.most_common()
        if count >= 3
    ]
    return error_rows, repeat_rows


def render_diagnostics(
    session_id: str,
    events: list[dict[str, Any]],
    *,
    limit: int,
) -> None:
    """Print diagnostic output for a session given a pre-fetched events list."""
    error_rows, repeat_rows = diagnostic_rows(events)
    row_limit = max(limit, 1)
    print(
        f"DIAG session={session_id[:8]} events_sampled={len(events)} "
        f"errors={len(error_rows)} repeats={len(repeat_rows)}"
    )
    _print_rows("ERR", error_rows[:row_limit])
    _print_rows(
        "REPEAT",
        repeat_rows[: max(row_limit - min(len(error_rows), row_limit), 0)],
    )


def _print_rows(prefix: str, rows: list[tuple[str, int, dict[str, Any]]]) -> None:
    for signature, count, event in rows:
        print(
            f"{prefix} x{count}|type={event.get('event_type', '-')}|"
            f"tool={event.get('tool_name', '-')}|{signature}"
        )
