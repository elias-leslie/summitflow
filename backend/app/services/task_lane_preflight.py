"""Live lane/workstream conflict checks via Agent Hub session inventory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

import httpx

from ..logging_config import get_logger
from ..storage import tasks as task_store
from ..storage.task_spirit import get_task_spirit
from ._agent_hub_config import AGENT_HUB_URL, build_agent_hub_headers

logger = get_logger(__name__)

_RETIRED_WORKSTREAMS = {"retired", "superseded"}
_TERMINAL_TASK_STATUSES = {"blocked", "completed", "cancelled", "abandoned", "failed"}
_LIST_SESSIONS_TIMEOUT = 10.0
_STALE_ACTIVE_MINUTES = 4 * 60


@dataclass
class TaskLaneConflictCheck:
    """Result of a live lane conflict check."""

    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    conflicting_tasks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _TaskScope:
    task_id: str
    paths: frozenset[str]


def _fetch_active_project_sessions(project_id: str) -> list[dict[str, Any]]:
    headers = build_agent_hub_headers(default_request_source="summitflow-task-lane-preflight")
    params = {"project_id": project_id, "status": "active", "page_size": 100}
    url = f"{AGENT_HUB_URL}/api/sessions"
    with httpx.Client(timeout=_LIST_SESSIONS_TIMEOUT) as client:
        response = client.get(url, headers=headers, params=params)
    response.raise_for_status()
    payload = response.json()
    sessions = payload.get("sessions", [])
    return sessions if isinstance(sessions, list) else []


def _is_live_lane_session(session: dict[str, Any]) -> bool:
    if session.get("workstream_status") in _RETIRED_WORKSTREAMS:
        return False
    return bool(session.get("external_id") or session.get("current_branch"))


def _lane_task_id(session: dict[str, Any]) -> str | None:
    """Infer the task id associated with a live lane session."""
    external_id = session.get("external_id")
    if isinstance(external_id, str) and external_id.startswith("task-"):
        return external_id

    branch = session.get("current_branch")
    if not isinstance(branch, str):
        return None
    branch_prefix = branch.split("/", 1)[0]
    if branch_prefix.startswith("task-"):
        return branch_prefix
    return None


def _is_terminal_task_lane(task_id: str | None) -> bool:
    if not task_id:
        return False
    task = task_store.get_task(task_id)
    if not task:
        return False
    return str(task.get("status") or "").lower() in _TERMINAL_TASK_STATUSES


def _lane_location(session: dict[str, Any]) -> str:
    working_dir = session.get("working_dir")
    if isinstance(working_dir, str) and working_dir:
        lane_kind = "worktree" if bool(session.get("is_worktree")) else "repo"
        return f"{lane_kind} {working_dir}"
    branch = session.get("current_branch")
    if isinstance(branch, str) and branch:
        return f"branch {branch}"
    return f"session {session.get('id') or 'unknown'}"


def _lane_summary(session: dict[str, Any]) -> str:
    session_id = str(session.get("id") or "unknown session")
    branch = session.get("current_branch")
    branch_suffix = f" on {branch}" if isinstance(branch, str) and branch else ""
    return f"{session_id} in {_lane_location(session)}{branch_suffix}"


def _parse_session_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _lane_age_minutes(session: dict[str, Any]) -> int | None:
    timestamp = _parse_session_timestamp(session.get("updated_at")) or _parse_session_timestamp(
        session.get("created_at")
    )
    if timestamp is None:
        return None
    return int((datetime.now(UTC) - timestamp).total_seconds() / 60)


def _is_stale_lane_session(session: dict[str, Any]) -> bool:
    age_minutes = _lane_age_minutes(session)
    return age_minutes is not None and age_minutes >= _STALE_ACTIVE_MINUTES


def _normalize_scope_entry(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    path = value.strip()
    if not path:
        return None
    while path.startswith("./"):
        path = path[2:]
    if not path or path.startswith("/"):
        return None
    if "\\" in path or "//" in path or path.endswith("/"):
        return None
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    normalized = str(PurePosixPath(path))
    if normalized == "." or normalized.endswith("/"):
        return None
    return normalized


def _load_task_scope(task_id: str) -> _TaskScope | None:
    spirit = get_task_spirit(task_id)
    if not spirit:
        return None
    context = spirit.get("context")
    if not isinstance(context, dict):
        return None

    merged: set[str] = set()
    saw_list = False
    for scope_field in ("files_to_modify", "files_to_create"):
        values = context.get(scope_field)
        if values is None:
            continue
        if not isinstance(values, list):
            return None
        saw_list = True
        for raw in values:
            normalized = _normalize_scope_entry(raw)
            if normalized is None:
                return None
            merged.add(normalized)

    if not saw_list or not merged:
        return None
    return _TaskScope(task_id=task_id, paths=frozenset(sorted(merged)))


def check_task_lane_conflicts(task_id: str, project_id: str) -> TaskLaneConflictCheck:
    """Check whether active Agent Hub lanes conflict with autonomous dispatch."""
    try:
        sessions = _fetch_active_project_sessions(project_id)
    except Exception as e:
        logger.warning("task_lane_preflight_failed", task_id=task_id, project_id=project_id, error=str(e))
        return TaskLaneConflictCheck()

    same_task_sessions: list[dict[str, Any]] = []
    other_lane_sessions: list[dict[str, Any]] = []
    for session in sessions:
        if not _is_live_lane_session(session):
            continue
        lane_task_id = _lane_task_id(session)
        if _is_terminal_task_lane(lane_task_id):
            continue
        if lane_task_id == task_id:
            same_task_sessions.append(session)
            continue
        if lane_task_id:
            other_lane_sessions.append(session)

    issues: list[str] = []
    suggestions: list[str] = []
    conflicting_tasks: list[str] = []

    if same_task_sessions:
        session = same_task_sessions[0]
        if _is_stale_lane_session(session):
            issues.append(f"Task already has a likely stale active lane: {_lane_summary(session)}")
            suggestions.append(
                f"Inspect the lane with `st sessions list --status active --project {project_id}` "
                "and reconcile or retire it before queueing another execution."
            )
        else:
            issues.append(f"Task already has an active lane: {_lane_summary(session)}")
            suggestions.append("Wait for the active lane to finish or reconcile it before queueing another execution.")

    if other_lane_sessions:
        target_scope = _load_task_scope(task_id)
        lane_sessions = sorted(
            other_lane_sessions,
            key=lambda session: (
                _is_stale_lane_session(session),
                str(_lane_task_id(session) or ""),
                str(session.get("id") or ""),
            ),
        )
        stale_present = any(_is_stale_lane_session(session) for session in lane_sessions)

        if stale_present:
            conflicting_tasks = [
                lane_task_id
                for session in lane_sessions
                if _is_stale_lane_session(session) and (lane_task_id := _lane_task_id(session))
            ]
            preview = ", ".join(conflicting_tasks[:3])
            lane_preview = "; ".join(_lane_summary(session) for session in lane_sessions[:2])
            issues.append(f"Another likely stale active coding lane exists in project {project_id}: {preview}")
            if lane_preview:
                suggestions.append(f"Active lane details: {lane_preview}")
            suggestions.append(
                f"Inspect the lane with `st sessions list --status active --project {project_id}` "
                "and retire or reconcile it if the session is no longer truly live."
            )
        else:
            if target_scope is None:
                chosen_session = lane_sessions[0]
                chosen_task_id = _lane_task_id(chosen_session)
                lane_preview = "; ".join(_lane_summary(session) for session in lane_sessions[:2])
                conflicting_tasks = [chosen_task_id] if chosen_task_id else []
                issues.append(
                    f"Another active coding lane exists in project {project_id} but lacks usable file scope: "
                    f"{task_id}"
                )
                if lane_preview:
                    suggestions.append(f"Active lane details: {lane_preview}")
                suggestions.append(
                    "Target task scope unavailable; keep the current project-level guard and finish, retire, "
                    "or scope the active lane before dispatching another coding task."
                )
            else:
                scope_unavailable_task_id: str | None = None
                exact_overlap_task_id: str | None = None
                exact_overlaps: list[str] = []
                for session in lane_sessions:
                    lane_task_id = _lane_task_id(session)
                    active_scope = _load_task_scope(lane_task_id) if lane_task_id else None
                    if active_scope is None:
                        scope_unavailable_task_id = lane_task_id or "unknown task"
                        break
                    overlaps = sorted(target_scope.paths & active_scope.paths)
                    if overlaps:
                        exact_overlap_task_id = lane_task_id
                        exact_overlaps = overlaps
                        break

                if scope_unavailable_task_id:
                    conflicting_tasks = [scope_unavailable_task_id]
                    lane_preview = "; ".join(_lane_summary(session) for session in lane_sessions[:2])
                    issues.append(
                        f"Another active coding lane exists in project {project_id} but lacks usable file scope: "
                        f"{scope_unavailable_task_id}"
                    )
                    if lane_preview:
                        suggestions.append(f"Active lane details: {lane_preview}")
                    suggestions.append(
                        "Active lane scope unavailable; keep the current project-level guard and finish, retire, "
                        "or scope the active lane before dispatching another coding task."
                    )
                elif exact_overlap_task_id:
                    conflicting_tasks = [exact_overlap_task_id]
                    overlap_preview = ", ".join(exact_overlaps[:3])
                    issues.append(
                        f"Another active coding lane overlaps exact files in project {project_id}: "
                        f"{exact_overlap_task_id} ({overlap_preview})"
                    )
                    suggestions.append(
                        f"Exact-file overlap with {exact_overlap_task_id}: {overlap_preview}. "
                        "Finish or retire the active lane before dispatching another coding task."
                    )

    return TaskLaneConflictCheck(
        issues=issues,
        suggestions=suggestions,
        conflicting_tasks=conflicting_tasks,
    )
