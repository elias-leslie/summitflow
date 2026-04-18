"""Session deduplication helpers for project pulse."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.utils.datetime_helpers import parse_iso_datetime

_TMUX_ID_PREFIX = "tmux:"
_TMUX_MODEL_SUFFIX = "/external-tmux"
_TMUX_METADATA_SOURCE = "terminal_tmux_sync"


def _first_nonempty(session: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = session.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _session_provider(session: dict[str, Any]) -> str:
    return _first_nonempty(session, ("effective_provider", "provider", "requested_provider"))


def _session_location(session: dict[str, Any]) -> str:
    return _first_nonempty(session, ("working_dir", "repo_root"))


def _session_freshness(session: dict[str, Any]) -> datetime:
    live_activity = session.get("live_activity")
    if isinstance(live_activity, dict):
        last_heartbeat = parse_iso_datetime(live_activity.get("last_heartbeat_at"))
        if last_heartbeat is not None:
            return last_heartbeat
    updated_at = parse_iso_datetime(session.get("updated_at"))
    return updated_at or datetime.fromtimestamp(0, UTC)


def _is_tmux_presence_session(session: dict[str, Any]) -> bool:
    session_id = str(session.get("id") or "")
    if session_id.startswith(_TMUX_ID_PREFIX):
        return True
    model = str(session.get("effective_model") or session.get("model") or session.get("requested_model") or "")
    if model.endswith(_TMUX_MODEL_SUFFIX):
        return True
    metadata = session.get("provider_metadata")
    return isinstance(metadata, dict) and metadata.get("source") == _TMUX_METADATA_SOURCE


def _active_session_dedupe_key(session: dict[str, Any]) -> tuple[str, str, str] | None:
    provider = _session_provider(session)
    location = _session_location(session)
    branch = str(session.get("current_branch") or "")
    if not provider or not location:
        return None
    return provider, location, branch


def _should_prefer_active_session(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
    candidate_is_tmux = _is_tmux_presence_session(candidate)
    current_is_tmux = _is_tmux_presence_session(current)
    if candidate_is_tmux != current_is_tmux:
        return not candidate_is_tmux
    return _session_freshness(candidate) >= _session_freshness(current)


def _dedupe_active_sessions(raw_sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[tuple[str, str, str], tuple[int, dict[str, Any]]] = {}
    passthrough: list[tuple[int, dict[str, Any]]] = []

    for index, session in enumerate(raw_sessions):
        key = _active_session_dedupe_key(session)
        if key is None:
            passthrough.append((index, session))
            continue
        current = selected.get(key)
        if current is None:
            selected[key] = (index, session)
            continue
        if _should_prefer_active_session(session, current[1]):
            selected[key] = (current[0], session)

    ordered = list(selected.values()) + passthrough
    ordered.sort(key=lambda item: item[0])
    return [session for _, session in ordered]
