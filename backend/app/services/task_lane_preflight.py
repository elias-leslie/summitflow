"""Live session/workstream conflict checks via Agent Hub session inventory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TypedDict

from ..logging_config import get_logger
from ..storage import tasks as task_store
from ._lane_inventory import (
    SpecialistSummary,
    fetch_live_project_inventory,
    summarize_active_specialists,
)
from ._lane_scope import (
    _SHARED_PLUMBING_PREFIXES,
    _UNKNOWN_TASK,
    classify_lane_scopes,
    find_scope_overlap,
    load_task_scope,
)

logger = get_logger(__name__)

# -- Constants --

_RETIRED_WORKSTREAMS: frozenset[str] = frozenset({"retired", "superseded"})
_FINAL_TASK_STATUSES: frozenset[str] = frozenset(
    {"completed", "cancelled", "failed"}
)
_STALE_ACTIVE_MINUTES = 10
_SESSIONS_INSPECT_CMD = "st sessions list --status active --project {project_id}"

# Disposition values
_ALLOW = "allow"
_BLOCK = "block"
_WARN = "warn"
_RECONCILE = "reconcile"

# Overlap kind values
_SAME_TASK = "same_task"
_STALE_SAME_TASK = "stale_same_task"
_STALE_LANE = "stale_lane"
_EXACT_FILE = "exact_file"
_SHARED_PLUMBING = "shared_plumbing"
_SHARED_CHECKOUT = "shared_checkout"
_READ_OVERLAP = "read_overlap"
_UNSCOPED_LANE = "unscoped_lane"
_UNSCOPED_TARGET = "unscoped_target"

# Ownership
_OWNERSHIP_KIND_STALE = "stale"


# -- Public result types --

# Re-export for backward compatibility
_SpecialistSummary = SpecialistSummary


class TaskLaneConflictCheckDict(TypedDict):
    issues: list[str]
    suggestions: list[str]
    conflicting_tasks: list[str]
    overlap_kind: str | None
    overlap_paths: list[str]
    shared_plumbing: bool
    disposition: str
    owner_session_id: str | None
    owner_branch: str | None
    owner_location: str | None
    active_specialists: list[SpecialistSummary]


@dataclass
class TaskLaneConflictCheck:
    """Result of a live session conflict check."""

    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    conflicting_tasks: list[str] = field(default_factory=list)
    overlap_kind: str | None = None
    overlap_paths: list[str] = field(default_factory=list)
    shared_plumbing: bool = False
    disposition: str = _ALLOW
    owner_session_id: str | None = None
    owner_branch: str | None = None
    owner_location: str | None = None
    active_specialists: list[SpecialistSummary] = field(default_factory=list)

    def to_dict(self) -> TaskLaneConflictCheckDict:
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


# -- Session metadata helpers --


def _lane_task_id(session: dict[str, object]) -> str | None:
    """Infer the task id associated with a live task session."""
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
    return branch_prefix if branch_prefix.startswith("task-") else None


def _task_status(task_id: str | None) -> str | None:
    """Return normalized task status when the task exists."""
    if not task_id:
        return None
    task = task_store.get_task(task_id)
    if not task:
        return None
    status = task.get("status")
    return str(status).lower() if status is not None else None


def _lane_summary(session: dict[str, object]) -> str:
    session_id = str(session.get("id") or "unknown session")
    working_dir = session.get("working_dir")
    branch = session.get("current_branch")
    if isinstance(working_dir, str) and working_dir:
        location = f"checkout {working_dir}"
    elif isinstance(branch, str) and branch:
        location = f"branch {branch}"
    else:
        location = f"session {session.get('id') or 'unknown'}"
    branch_suffix = f" on {branch}" if isinstance(branch, str) and branch else ""
    return f"{session_id} in {location}{branch_suffix}"


def _is_stale_lane_session(session: dict[str, object]) -> bool:
    if session.get("ownership_kind") == _OWNERSHIP_KIND_STALE:
        return True
    raw = session.get("updated_at") or session.get("created_at")
    if not isinstance(raw, str) or not raw:
        return False
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    ts = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    age_minutes = int((datetime.now(UTC) - ts).total_seconds() / 60)
    return age_minutes >= _STALE_ACTIVE_MINUTES


def _set_owner_from_session(result: TaskLaneConflictCheck, session: dict[str, object]) -> None:
    """Populate owner_session_id, owner_branch, and owner_location from a session."""
    result.owner_session_id = str(session.get("id") or "")
    branch = session.get("current_branch")
    result.owner_branch = branch if isinstance(branch, str) else None
    result.owner_location = _lane_summary(session)


# -- Conflict detection --


def _apply_same_task_conflict(
    result: TaskLaneConflictCheck, task_id: str, project_id: str, sessions: list[dict[str, object]]
) -> None:
    session = sessions[0]
    _set_owner_from_session(result, session)

    target_status = _task_status(task_id)
    if target_status in _FINAL_TASK_STATUSES:
        result.overlap_kind = _STALE_SAME_TASK
        result.disposition = _RECONCILE
        result.issues.append(
            f"Task status is {target_status} but it still has a leftover live session: {_lane_summary(session)}"
        )
        result.suggestions.append(
            "Reconcile or retire the leftover same-task session before redispatching or treating "
            "the task as cleanly closed."
        )
    elif _is_stale_lane_session(session):
        result.overlap_kind = _STALE_SAME_TASK
        result.disposition = _RECONCILE
        result.issues.append(f"Task already has a likely stale active session: {_lane_summary(session)}")
        result.suggestions.append(
            f"Inspect the active session with `{_SESSIONS_INSPECT_CMD.format(project_id=project_id)}` "
            "and reconcile or retire it before queueing another execution."
        )
    else:
        result.overlap_kind = _SAME_TASK
        result.disposition = _BLOCK
        result.issues.append(f"Task already has an active session: {_lane_summary(session)}")
        result.suggestions.append(
            "Wait for the active session to finish or reconcile it before queueing another execution."
        )


def _apply_unscoped_conflict(
    result: TaskLaneConflictCheck,
    overlap_kind: str,
    display_id: str,
    project_id: str,
    lane_sessions: list[dict[str, object]],
    suggestion_prefix: str,
) -> None:
    """Handle both unscoped-target and unscoped-session conflicts."""
    chosen = lane_sessions[0]
    chosen_task_id = _lane_task_id(chosen)
    _set_owner_from_session(result, chosen)
    lane_preview = "; ".join(_lane_summary(s) for s in lane_sessions[:2])
    result.conflicting_tasks = [chosen_task_id] if chosen_task_id else []
    result.overlap_kind = overlap_kind
    result.disposition = _WARN
    result.issues.append(
        f"Another active coding session exists in project {project_id} but lacks usable file scope: {display_id}"
    )
    if lane_preview:
        result.suggestions.append(f"Active session details: {lane_preview}")
    result.suggestions.append(
        f"{suggestion_prefix}; keep the current project-level guard and finish, retire, "
        "or scope the active session before dispatching another coding task."
    )


def _apply_write_overlap_conflict(
    result: TaskLaneConflictCheck,
    project_id: str,
    lane_sessions: list[dict[str, object]],
    overlap_id: str,
    overlaps: list[str],
    is_pure_plumbing: bool,
) -> None:
    """Handle exact-file or shared-plumbing write overlap."""
    owner_session = next(s for s in lane_sessions if _lane_task_id(s) == overlap_id)
    _set_owner_from_session(result, owner_session)
    result.conflicting_tasks = [overlap_id]
    result.overlap_paths = overlaps
    result.disposition = _BLOCK
    preview = ", ".join(overlaps[:3])

    if is_pure_plumbing:
        result.overlap_kind = _SHARED_PLUMBING
        result.shared_plumbing = True
        result.issues.append(
            f"Another active coding session is already modifying shared plumbing in project {project_id}: "
            f"{overlap_id} ({preview})"
        )
        result.suggestions.append(
            f"Shared-plumbing overlap with {overlap_id}: {preview}. "
            "Do not run parallel coding sessions in adapters/tooling/orchestration areas; finish or retire "
            "the active session first."
        )
        return

    is_plumbing_overlap = any(
        p.startswith(prefix) for p in overlaps for prefix in _SHARED_PLUMBING_PREFIXES
    )
    if is_plumbing_overlap:
        result.overlap_kind = _SHARED_PLUMBING
        result.shared_plumbing = True
        result.issues.append(
            f"Another active coding session overlaps shared plumbing files in project {project_id}: "
            f"{overlap_id} ({preview})"
        )
    else:
        result.overlap_kind = _EXACT_FILE
        result.issues.append(
            f"Another active coding session overlaps exact files in project {project_id}: "
            f"{overlap_id} ({preview})"
        )
    result.suggestions.append(
        f"Exact-file overlap with {overlap_id}: {preview}. "
        "Finish or retire the active session before dispatching another coding task."
    )


def _apply_read_overlap_conflict(
    result: TaskLaneConflictCheck,
    project_id: str,
    lane_sessions: list[dict[str, object]],
    overlap_id: str,
    overlap_paths: list[str],
) -> None:
    """Handle read-only scope overlap (warn, not block)."""
    chosen = next(s for s in lane_sessions if _lane_task_id(s) == overlap_id)
    _set_owner_from_session(result, chosen)
    result.conflicting_tasks = [overlap_id]
    result.overlap_kind = _READ_OVERLAP
    result.overlap_paths = overlap_paths
    result.disposition = _WARN
    preview = ", ".join(overlap_paths[:3])
    result.issues.append(
        f"Another active coding session is reading files in the target scope in project {project_id}: "
        f"{overlap_id} ({preview})"
    )
    result.suggestions.append(
        f"Read-scope overlap with {overlap_id}: {preview}. Coordinate before editing if that session "
        "may promote into writes, but safe parallel work can continue."
    )


def _apply_stale_lane_conflict(
    result: TaskLaneConflictCheck,
    project_id: str,
    lane_sessions: list[dict[str, object]],
    stale_sessions: list[dict[str, object]],
) -> None:
    """Handle stale active task sessions."""
    _set_owner_from_session(result, stale_sessions[0])
    result.overlap_kind = _STALE_LANE
    result.disposition = _RECONCILE
    result.conflicting_tasks = [t for s in stale_sessions if (t := _lane_task_id(s))]
    preview = ", ".join(result.conflicting_tasks[:3])
    lane_preview = "; ".join(_lane_summary(s) for s in lane_sessions[:2])
    result.issues.append(
        f"Another likely stale active coding session exists in project {project_id}: {preview}"
    )
    if lane_preview:
        result.suggestions.append(f"Active session details: {lane_preview}")
    result.suggestions.append(
        f"Inspect the active session with `{_SESSIONS_INSPECT_CMD.format(project_id=project_id)}` "
        "and retire or reconcile it if the session is no longer truly live."
    )


def _apply_scoped_conflict(
    result: TaskLaneConflictCheck,
    task_id: str,
    project_id: str,
    lane_sessions: list[dict[str, object]],
    target_scope,
) -> None:
    scoped, unscoped_ids = classify_lane_scopes(lane_sessions, _lane_task_id)
    scoped = sorted(scoped, key=lambda item: item[0])
    overlap_id, overlap_paths, overlap_kind = find_scope_overlap(target_scope, scoped)

    if overlap_kind == "read":
        assert overlap_id is not None
        _apply_read_overlap_conflict(result, project_id, lane_sessions, overlap_id, overlap_paths)
    elif overlap_id is not None:
        _apply_write_overlap_conflict(
            result, project_id, lane_sessions, overlap_id, overlap_paths, overlap_kind == "plumbing"
        )
    elif not scoped and unscoped_ids:
        chosen_id = sorted(unscoped_ids)[0]
        chosen_sessions = [s for s in lane_sessions if (_lane_task_id(s) or _UNKNOWN_TASK) == chosen_id]
        _apply_unscoped_conflict(
            result, _UNSCOPED_LANE, chosen_id, project_id, chosen_sessions or lane_sessions,
            "Active session scope unavailable",
        )


def _apply_other_lane_conflict(
    result: TaskLaneConflictCheck,
    task_id: str,
    project_id: str,
    sessions: list[dict[str, object]],
) -> None:
    lane_sessions = sorted(
        sessions,
        key=lambda s: (_is_stale_lane_session(s), str(_lane_task_id(s) or ""), str(s.get("id") or "")),
    )
    stale_sessions = [s for s in lane_sessions if _is_stale_lane_session(s)]

    if stale_sessions:
        _apply_stale_lane_conflict(result, project_id, lane_sessions, stale_sessions)
        return

    primary = lane_sessions[0]
    _set_owner_from_session(result, primary)
    owner_task = _lane_task_id(primary)
    result.overlap_kind = _SHARED_CHECKOUT
    result.disposition = _BLOCK
    result.conflicting_tasks = [owner_task] if owner_task else []
    result.issues.append(
        f"Another active coding session already owns the shared checkout for project {project_id}: {_lane_summary(primary)}"
    )
    result.suggestions.append(
        "Shared-checkout mode does not allow parallel same-project coding sessions. "
        "Finish, retire, or reconcile the active session before dispatching another task."
    )
    return

# -- Session partitioning --


def _partition_sessions(
    sessions: list[dict[str, object]], task_id: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Partition sessions into same-task and other-active-task sessions."""
    same_task: list[dict[str, object]] = []
    other_lanes: list[dict[str, object]] = []
    for session in sessions:
        if session.get("workstream_status") in _RETIRED_WORKSTREAMS:
            continue
        if not (session.get("external_id") or session.get("current_branch")):
            continue
        lane_id = _lane_task_id(session)
        if lane_id == task_id:
            same_task.append(session)
        elif lane_id and _task_status(lane_id) not in _FINAL_TASK_STATUSES:
            other_lanes.append(session)
    return same_task, other_lanes


# -- Public API --


def check_task_lane_conflicts(task_id: str, project_id: str) -> TaskLaneConflictCheck:
    """Check whether active Agent Hub sessions conflict with autonomous dispatch."""
    try:
        sessions, specialists = fetch_live_project_inventory(project_id)
    except Exception as e:
        logger.warning("task_lane_preflight_failed", task_id=task_id, project_id=project_id, error=str(e))
        return TaskLaneConflictCheck()

    same_task_sessions, other_lane_sessions = _partition_sessions(sessions, task_id)
    result = TaskLaneConflictCheck(active_specialists=summarize_active_specialists(specialists))

    if same_task_sessions:
        _apply_same_task_conflict(result, task_id, project_id, same_task_sessions)

    if other_lane_sessions:
        stale_other_lane_sessions = [s for s in other_lane_sessions if _is_stale_lane_session(s)]
        if stale_other_lane_sessions:
            _apply_stale_lane_conflict(result, project_id, other_lane_sessions, stale_other_lane_sessions)
            return result
        target_scope = load_task_scope(task_id)
        if target_scope is None:
            _apply_unscoped_conflict(
                result,
                _UNSCOPED_TARGET,
                task_id,
                project_id,
                other_lane_sessions,
                "Target task scope unavailable",
            )
        else:
            _apply_scoped_conflict(result, task_id, project_id, other_lane_sessions, target_scope)

    return result
