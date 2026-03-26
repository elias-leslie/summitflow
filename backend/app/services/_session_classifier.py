"""Session classification, normalization, and bucketing for project pulse."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.services._session_dedupe import _dedupe_active_sessions
from app.utils.datetime_helpers import parse_iso_datetime

_LIVE_LIFECYCLE_STATES = {"active", "quiet", "stalled"}
_STALE_LIFECYCLE_STATES = {"dead_candidate", "reapable"}
_TERMINAL_HEALTH_STATES = {"completed", "failed", "error"}
_ACTIVE_BUCKET = "active"
_STALE_BUCKET = "stale"
_REAPABLE_STATE = "reapable"
_TASK_ID_PREFIX = "task-"
_ACTIVE_AGE_SECS = 30 * 60
_STALE_AGE_SECS = 6 * 60 * 60


def _normalize_active_session(
    session: dict[str, Any],
    owner_session_ids: set[str],
    specialist_session_ids: set[str],
) -> dict[str, Any]:
    """Return the session fields relevant for coordination summaries."""
    session_id = str(session.get("id") or "")
    if session_id in owner_session_ids:
        lane_role = "owner"
    elif session_id in specialist_session_ids:
        lane_role = "specialist"
    else:
        lane_role = "observer"

    return {
        "id": session_id,
        "lane_role": lane_role,
        "status": session.get("status"),
        "session_type": session.get("session_type"),
        "agent_slug": session.get("agent_slug"),
        "client_id": session.get("client_id"),
        "request_source": session.get("request_source"),
        "source_client": session.get("source_client"),
        "source_path": session.get("source_path"),
        "parent_session_id": session.get("parent_session_id"),
        "external_id": session.get("external_id"),
        "current_branch": session.get("current_branch"),
        "working_dir": session.get("working_dir"),
        "worktree_path": session.get("worktree_path"),
        "repo_root": session.get("repo_root"),
        "host": session.get("host"),
        "tmux_session_name": session.get("tmux_session_name"),
        "scope_confidence": session.get("scope_confidence"),
        "declared_scope_paths": session.get("declared_scope_paths") or [],
        "observed_read_paths": session.get("observed_read_paths") or [],
        "observed_write_paths": session.get("observed_write_paths") or [],
        "requested_model": session.get("requested_model"),
        "effective_model": session.get("effective_model") or session.get("model"),
        "fallback_used": bool(session.get("fallback_used")),
        "fallback_reason": session.get("fallback_reason"),
        "summary_oneliner": session.get("summary_oneliner"),
        "updated_at": session.get("updated_at"),
        "live_activity": session.get("live_activity"),
    }


def _classify_session_coordination_bucket(session: dict[str, Any]) -> str | None:
    """Classify a raw session for pulse summaries."""
    live_activity = session.get("live_activity")
    if isinstance(live_activity, dict):
        lifecycle_state = str(live_activity.get("lifecycle_state") or "").strip()
        if lifecycle_state in _LIVE_LIFECYCLE_STATES:
            return _ACTIVE_BUCKET
        if lifecycle_state in _STALE_LIFECYCLE_STATES:
            return _STALE_BUCKET
        health = str(live_activity.get("health") or "").strip()
        if health in _LIVE_LIFECYCLE_STATES:
            return _ACTIVE_BUCKET
        if health in _TERMINAL_HEALTH_STATES:
            return None

    updated_at = parse_iso_datetime(session.get("updated_at"))
    if updated_at is None:
        return None
    age_seconds = (datetime.now(UTC) - updated_at).total_seconds()
    if age_seconds <= _ACTIVE_AGE_SECS:
        return _ACTIVE_BUCKET
    if age_seconds >= _STALE_AGE_SECS:
        return _STALE_BUCKET
    return None


def _session_linked_task_id(session: dict[str, Any]) -> str:
    """Return the task-xxx ID linked to a session via external_id or branch, or empty string."""
    external_id = str(session.get("external_id") or "")
    if external_id.startswith(_TASK_ID_PREFIX):
        return external_id
    branch = str(session.get("current_branch") or "")
    first_segment = branch.split("/")[0]
    if first_segment.startswith(_TASK_ID_PREFIX):
        return first_segment
    return ""


def _bucket_sessions(
    raw_sessions: list[dict[str, Any]],
    owner_session_ids: set[str],
    specialist_session_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    """Classify raw sessions; return (active_sessions, stale_sessions, session_linked_task_ids)."""
    active_raw: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    for session in raw_sessions:
        if not isinstance(session, dict):
            continue
        bucket = _classify_session_coordination_bucket(session)
        if bucket == _ACTIVE_BUCKET:
            active_raw.append(session)
        elif bucket == _STALE_BUCKET:
            stale.append(_normalize_active_session(session, owner_session_ids, specialist_session_ids))
    active = [
        _normalize_active_session(s, owner_session_ids, specialist_session_ids)
        for s in _dedupe_active_sessions(active_raw)
    ]
    linked_ids = {task_id for s in active_raw if (task_id := _session_linked_task_id(s))}
    return active, stale, linked_ids


def _count_reapable(stale_sessions: list[dict[str, Any]]) -> int:
    """Count stale sessions marked reapable via boolean flag or lifecycle_state."""
    return sum(
        1 for s in stale_sessions
        if isinstance(s.get("live_activity"), dict)
        and (
            bool(s["live_activity"].get("reapable"))
            or str(s["live_activity"].get("lifecycle_state") or "").strip() == _REAPABLE_STATE
        )
    )
