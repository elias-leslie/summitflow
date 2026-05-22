"""Session status filtering helpers for the sessions CLI commands."""

from __future__ import annotations

from typing import Any

_LIVE_STATUS_ALIASES = {"stale", "reapable"}


def normalize_status_filter(status_filter: str | None) -> str | None:
    """Normalize CLI-friendly session status aliases to Agent Hub values."""
    if not status_filter:
        return None
    normalized = status_filter.strip().lower()
    if normalized in {"running", "stale", "reapable"}:
        return "active"
    return normalized


def session_matches_status_alias(session: dict[str, Any], status_filter: str | None) -> bool:
    """Return True if the session matches the given status alias filter."""
    if not status_filter:
        return True
    normalized = status_filter.strip().lower()
    if normalized not in _LIVE_STATUS_ALIASES:
        return True
    live = session.get("live_activity")
    if not isinstance(live, dict):
        return False
    live_state = str(
        live.get("lifecycle_state")
        or live.get("status")
        or live.get("state")
        or session.get("status")
        or "-"
    ).strip().lower()
    if normalized == "reapable":
        return bool(live.get("reapable")) or live_state == "reapable"
    return (
        bool(live.get("is_stale"))
        or bool(live.get("reapable"))
        or live_state in {"reapable", "stale", "stalled"}
    )


def live_state(session: dict[str, Any]) -> str:
    """Return the live lifecycle state string for a session."""
    live = session.get("live_activity")
    if not isinstance(live, dict):
        return str(session.get("status") or "-")
    return str(
        live.get("lifecycle_state")
        or live.get("status")
        or live.get("state")
        or session.get("status")
        or "-"
    ).strip()
