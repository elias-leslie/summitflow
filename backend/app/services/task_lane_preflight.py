"""Live lane/workstream conflict checks via Agent Hub session inventory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from ..logging_config import get_logger
from ._agent_hub_config import AGENT_HUB_URL, build_agent_hub_headers

logger = get_logger(__name__)

_RETIRED_WORKSTREAMS = {"retired", "superseded"}
_LIST_SESSIONS_TIMEOUT = 10.0


@dataclass
class TaskLaneConflictCheck:
    """Result of a live lane conflict check."""

    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    conflicting_tasks: list[str] = field(default_factory=list)


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
        issues.append(
            f"Task already has an active lane: {session.get('id')} on {session.get('current_branch') or 'unknown branch'}"
        )
        suggestions.append("Wait for the active lane to finish or reconcile it before queueing another execution.")

    if other_lane_sessions:
        conflicting_tasks = [
            lane_task_id
            for session in other_lane_sessions
            if (lane_task_id := _lane_task_id(session))
        ]
        preview = ", ".join(conflicting_tasks[:3])
        issues.append(f"Another active coding lane exists in project {project_id}: {preview}")
        suggestions.append("Finish or retire the active lane before dispatching another coding task in this project.")

    return TaskLaneConflictCheck(
        issues=issues,
        suggestions=suggestions,
        conflicting_tasks=conflicting_tasks,
    )
