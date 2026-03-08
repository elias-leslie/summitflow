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
# Align stale-lane detection with Agent Hub completion-session cleanup so SummitFlow
# can reconcile abandoned task lanes shortly after Agent Hub would auto-complete them.
_STALE_ACTIVE_MINUTES = 10
_LIVE_OWNERSHIP_PATH = "/api/ownership/projects/{project_id}/live"
_LEGACY_SESSIONS_PATH = "/api/sessions"
_SHARED_PLUMBING_PREFIXES = (
    "backend/app/adapters/",
    "backend/app/api/complete/",
    "backend/app/services/tools/",
)


@dataclass
class TaskLaneConflictCheck:
    """Result of a live lane conflict check."""

    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    conflicting_tasks: list[str] = field(default_factory=list)
    overlap_kind: str | None = None
    overlap_paths: list[str] = field(default_factory=list)
    shared_plumbing: bool = False
    disposition: str = "allow"
    owner_session_id: str | None = None
    owner_branch: str | None = None
    owner_location: str | None = None
    active_specialists: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issues": self.issues,
            "suggestions": self.suggestions,
            "conflicting_tasks": self.conflicting_tasks,
            "overlap_kind": self.overlap_kind,
            "overlap_paths": self.overlap_paths,
            "shared_plumbing": self.shared_plumbing,
            "disposition": self.disposition,
            "owner_session_id": self.owner_session_id,
            "owner_branch": self.owner_branch,
            "owner_location": self.owner_location,
            "active_specialists": self.active_specialists,
        }


@dataclass(frozen=True)
class _TaskScope:
    task_id: str
    paths: frozenset[str]


def _fetch_live_project_inventory(
    project_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    headers = build_agent_hub_headers(default_request_source="summitflow-task-lane-preflight")
    with httpx.Client(timeout=_LIST_SESSIONS_TIMEOUT) as client:
        ownership_response = client.get(
            f"{AGENT_HUB_URL}{_LIVE_OWNERSHIP_PATH.format(project_id=project_id)}",
            headers=headers,
        )
        inventory = _decode_live_lane_payload(ownership_response)
        if inventory is not None:
            return inventory

        legacy_response = client.get(
            f"{AGENT_HUB_URL}{_LEGACY_SESSIONS_PATH}",
            headers=headers,
            params={"project_id": project_id, "status": "active", "page_size": 100},
        )
        legacy_response.raise_for_status()
        payload = legacy_response.json()
        sessions = payload.get("sessions", [])
        return (sessions if isinstance(sessions, list) else [], [])


def _decode_live_lane_payload(
    response: httpx.Response,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    status_code = getattr(response, "status_code", None)
    if status_code == 404:
        return None

    response.raise_for_status()
    payload = response.json()
    owners = payload.get("active_owners")
    specialists = payload.get("active_specialists")
    if isinstance(owners, list):
        owner_sessions = [_owner_to_session(owner) for owner in owners if isinstance(owner, dict)]
        specialist_rows = [row for row in specialists if isinstance(row, dict)] if isinstance(specialists, list) else []
        return owner_sessions, specialist_rows

    sessions = payload.get("sessions")
    if isinstance(sessions, list):
        return sessions, []
    return [], []


def _owner_to_session(owner: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": owner.get("session_id"),
        "external_id": owner.get("task_id"),
        "current_branch": owner.get("branch"),
        "working_dir": owner.get("worktree_path"),
        "is_worktree": bool(owner.get("is_worktree")),
        "status": owner.get("session_status"),
        "workstream_status": owner.get("workstream_status"),
        "workstream_note": owner.get("workstream_note"),
        "ownership_kind": owner.get("ownership_kind"),
        "scope_paths": owner.get("scope_paths") if isinstance(owner.get("scope_paths"), list) else [],
        "created_at": owner.get("created_at"),
        "updated_at": owner.get("updated_at"),
    }


def _summarize_active_specialists(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group live specialist sessions for context surfaces without changing blockers."""
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        agent_slug = str(row.get("agent_slug") or "unknown")
        age_minutes = int(row.get("age_minutes") or 0)
        summary = grouped.setdefault(
            agent_slug,
            {
                "agent_slug": agent_slug,
                "count": 0,
                "request_sources": set(),
                "session_ids": [],
                "newest_age_minutes": age_minutes,
                "oldest_age_minutes": age_minutes,
            },
        )
        summary["count"] += 1
        if row.get("request_source"):
            summary["request_sources"].add(str(row["request_source"]))
        if row.get("session_id"):
            summary["session_ids"].append(str(row["session_id"]))
        summary["newest_age_minutes"] = min(summary["newest_age_minutes"], age_minutes)
        summary["oldest_age_minutes"] = max(summary["oldest_age_minutes"], age_minutes)

    result: list[dict[str, Any]] = []
    for agent_slug, summary in grouped.items():
        result.append(
            {
                "agent_slug": agent_slug,
                "count": summary["count"],
                "request_sources": sorted(summary["request_sources"]),
                "session_ids": summary["session_ids"][:3],
                "newest_age_minutes": summary["newest_age_minutes"],
                "oldest_age_minutes": summary["oldest_age_minutes"],
            }
        )
    return sorted(result, key=lambda row: (-int(row["count"]), str(row["agent_slug"])))


def _is_live_lane_session(session: dict[str, Any]) -> bool:
    if session.get("workstream_status") in _RETIRED_WORKSTREAMS:
        return False
    return bool(session.get("external_id") or session.get("current_branch"))


def _lane_task_id(session: dict[str, Any]) -> str | None:
    """Infer the task id associated with a live lane session."""
    task_id = session.get("task_id")
    if isinstance(task_id, str) and task_id.startswith("task-"):
        return task_id

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
    if session.get("ownership_kind") == "stale":
        return True
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
    saw_scope_field = False
    for scope_field in ("files_to_modify", "files_to_create"):
        values = context.get(scope_field)
        if values is None:
            continue
        saw_scope_field = True
        if not isinstance(values, list):
            continue
        for raw in values:
            normalized = _normalize_scope_entry(raw)
            if normalized is None:
                continue
            merged.add(normalized)

    if not saw_scope_field or not merged:
        return None
    return _TaskScope(task_id=task_id, paths=frozenset(sorted(merged)))


def _shared_plumbing_paths(paths: frozenset[str]) -> list[str]:
    return sorted(
        path for path in paths if any(path.startswith(prefix) for prefix in _SHARED_PLUMBING_PREFIXES)
    )


def check_task_lane_conflicts(task_id: str, project_id: str) -> TaskLaneConflictCheck:
    """Check whether active Agent Hub lanes conflict with autonomous dispatch."""
    try:
        sessions, specialists = _fetch_live_project_inventory(project_id)
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
    overlap_kind: str | None = None
    overlap_paths: list[str] = []
    shared_plumbing = False
    disposition = "allow"
    owner_session_id: str | None = None
    owner_branch: str | None = None
    owner_location: str | None = None

    active_specialists = _summarize_active_specialists(specialists)

    if same_task_sessions:
        session = same_task_sessions[0]
        owner_session_id = str(session.get("id") or "")
        owner_branch = session.get("current_branch") if isinstance(session.get("current_branch"), str) else None
        owner_location = _lane_location(session)
        if _is_stale_lane_session(session):
            overlap_kind = "stale_same_task"
            disposition = "reconcile"
            issues.append(f"Task already has a likely stale active lane: {_lane_summary(session)}")
            suggestions.append(
                f"Inspect the lane with `st sessions list --status active --project {project_id}` "
                "and reconcile or retire it before queueing another execution."
            )
        else:
            overlap_kind = "same_task"
            disposition = "block"
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
            overlap_kind = "stale_lane"
            disposition = "reconcile"
            conflicting_tasks = [
                lane_task_id
                for session in lane_sessions
                if _is_stale_lane_session(session) and (lane_task_id := _lane_task_id(session))
            ]
            stale_session = next((session for session in lane_sessions if _is_stale_lane_session(session)), None)
            assert stale_session is not None, "stale_present guarantees at least one stale session"
            owner_session_id = str(stale_session.get("id") or "")
            owner_branch = (
                stale_session.get("current_branch")
                if isinstance(stale_session.get("current_branch"), str)
                else None
            )
            owner_location = _lane_location(stale_session)
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
                owner_session_id = str(chosen_session.get("id") or "")
                owner_branch = (
                    chosen_session.get("current_branch")
                    if isinstance(chosen_session.get("current_branch"), str)
                    else None
                )
                owner_location = _lane_location(chosen_session)
                lane_preview = "; ".join(_lane_summary(session) for session in lane_sessions[:2])
                conflicting_tasks = [chosen_task_id] if chosen_task_id else []
                overlap_kind = "unscoped_target"
                disposition = "warn"
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
                scoped_lane_entries: list[tuple[str, _TaskScope]] = []
                unscoped_lane_task_ids: list[str] = []
                exact_overlap_task_id: str | None = None
                exact_overlaps: list[str] = []
                shared_plumbing_task_id: str | None = None
                shared_plumbing_overlaps: list[str] = []
                target_shared_paths = _shared_plumbing_paths(target_scope.paths)
                for session in lane_sessions:
                    lane_task_id = _lane_task_id(session)
                    active_scope = _load_task_scope(lane_task_id) if lane_task_id else None
                    if active_scope is None:
                        unscoped_lane_task_ids.append(lane_task_id or "unknown task")
                        continue
                    scoped_lane_entries.append((lane_task_id or "unknown task", active_scope))

                for lane_task_id, active_scope in scoped_lane_entries:
                    overlaps = sorted(target_scope.paths & active_scope.paths)
                    if overlaps:
                        exact_overlap_task_id = lane_task_id
                        exact_overlaps = overlaps
                        break
                    if target_shared_paths:
                        active_shared_paths = _shared_plumbing_paths(active_scope.paths)
                        if active_shared_paths:
                            shared_plumbing_task_id = lane_task_id
                            shared_plumbing_overlaps = sorted(set(target_shared_paths) | set(active_shared_paths))
                            break

                if exact_overlap_task_id:
                    winning_session = next(
                        (session for session in lane_sessions if _lane_task_id(session) == exact_overlap_task_id),
                        None,
                    )
                    assert winning_session is not None, "exact_overlap_task_id was found in lane_sessions"
                    conflicting_tasks = [exact_overlap_task_id]
                    overlap_kind = "exact_file"
                    overlap_paths = exact_overlaps
                    disposition = "block"
                    owner_session_id = str(winning_session.get("id") or "")
                    owner_branch = (
                        winning_session.get("current_branch")
                        if isinstance(winning_session.get("current_branch"), str)
                        else None
                    )
                    owner_location = _lane_location(winning_session)
                    overlap_preview = ", ".join(exact_overlaps[:3])
                    if _shared_plumbing_paths(frozenset(exact_overlaps)):
                        overlap_kind = "shared_plumbing"
                        shared_plumbing = True
                        issues.append(
                            f"Another active coding lane overlaps shared plumbing files in project {project_id}: "
                            f"{exact_overlap_task_id} ({overlap_preview})"
                        )
                    else:
                        issues.append(
                            f"Another active coding lane overlaps exact files in project {project_id}: "
                            f"{exact_overlap_task_id} ({overlap_preview})"
                        )
                    suggestions.append(
                        f"Exact-file overlap with {exact_overlap_task_id}: {overlap_preview}. "
                        "Finish or retire the active lane before dispatching another coding task."
                    )
                elif shared_plumbing_task_id:
                    winning_session = next(
                        (session for session in lane_sessions if _lane_task_id(session) == shared_plumbing_task_id),
                        None,
                    )
                    assert winning_session is not None, "shared_plumbing_task_id was found in lane_sessions"
                    conflicting_tasks = [shared_plumbing_task_id]
                    overlap_kind = "shared_plumbing"
                    overlap_paths = shared_plumbing_overlaps
                    shared_plumbing = True
                    disposition = "block"
                    owner_session_id = str(winning_session.get("id") or "")
                    owner_branch = (
                        winning_session.get("current_branch")
                        if isinstance(winning_session.get("current_branch"), str)
                        else None
                    )
                    owner_location = _lane_location(winning_session)
                    overlap_preview = ", ".join(shared_plumbing_overlaps[:3])
                    issues.append(
                        f"Another active coding lane is already modifying shared plumbing in project {project_id}: "
                        f"{shared_plumbing_task_id} ({overlap_preview})"
                    )
                    suggestions.append(
                        f"Shared-plumbing overlap with {shared_plumbing_task_id}: {overlap_preview}. "
                        "Do not run parallel coding lanes in adapters/tooling/orchestration areas; finish or retire "
                        "the active lane first."
                    )
                elif scoped_lane_entries:
                    # At least one active lane is safely scoped and disjoint; ignore noisier unscoped lanes for phase 1.
                    pass
                elif unscoped_lane_task_ids:
                    chosen_task_id = sorted(unscoped_lane_task_ids)[0]
                    chosen_session = next(
                        (
                            session
                            for session in lane_sessions
                            if (_lane_task_id(session) or "unknown task") == chosen_task_id
                        ),
                        None,
                    )
                    assert chosen_session is not None, "chosen_task_id was derived from lane_sessions"
                    conflicting_tasks = [chosen_task_id]
                    overlap_kind = "unscoped_lane"
                    disposition = "warn"
                    owner_session_id = str(chosen_session.get("id") or "")
                    owner_branch = (
                        chosen_session.get("current_branch")
                        if isinstance(chosen_session.get("current_branch"), str)
                        else None
                    )
                    owner_location = _lane_location(chosen_session)
                    lane_preview = "; ".join(_lane_summary(session) for session in lane_sessions[:2])
                    issues.append(
                        f"Another active coding lane exists in project {project_id} but lacks usable file scope: "
                        f"{chosen_task_id}"
                    )
                    if lane_preview:
                        suggestions.append(f"Active lane details: {lane_preview}")
                    suggestions.append(
                        "Active lane scope unavailable; keep the current project-level guard and finish, retire, "
                        "or scope the active lane before dispatching another coding task."
                    )

    return TaskLaneConflictCheck(
        issues=issues,
        suggestions=suggestions,
        conflicting_tasks=conflicting_tasks,
        overlap_kind=overlap_kind,
        overlap_paths=overlap_paths,
        shared_plumbing=shared_plumbing,
        disposition=disposition,
        owner_session_id=owner_session_id,
        owner_branch=owner_branch,
        owner_location=owner_location,
        active_specialists=active_specialists,
    )
