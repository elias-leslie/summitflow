"""Live lane/workstream conflict checks via Agent Hub session inventory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any, TypedDict

import httpx

from ..logging_config import get_logger
from ..storage import tasks as task_store
from ..storage.task_spirit import get_task_spirit
from ._agent_hub_config import AGENT_HUB_URL, build_agent_hub_headers

logger = get_logger(__name__)

# -- Constants --

_RETIRED_WORKSTREAMS: frozenset[str] = frozenset({"retired", "superseded"})
_TERMINAL_TASK_STATUSES: frozenset[str] = frozenset(
    {"blocked", "completed", "cancelled", "abandoned", "failed"}
)
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
_READ_OVERLAP = "read_overlap"
_UNSCOPED_LANE = "unscoped_lane"
_UNSCOPED_TARGET = "unscoped_target"

# Ownership / scope confidence literals
_OWNERSHIP_KIND_STALE = "stale"
_SCOPE_CONFIDENCE_OBSERVED_READ = "observed_read"
_UNKNOWN_TASK = "unknown task"

# -- Public result types --


class _SpecialistSummary(TypedDict):
    agent_slug: str
    count: int
    request_sources: list[str]
    session_ids: list[str]
    newest_age_minutes: int
    oldest_age_minutes: int


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
    active_specialists: list[_SpecialistSummary]


@dataclass
class TaskLaneConflictCheck:
    """Result of a live lane conflict check."""

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
    active_specialists: list[_SpecialistSummary] = field(default_factory=list)

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


# -- Internal scope types --


@dataclass(frozen=True)
class _TaskScope:
    task_id: str
    paths: frozenset[str]


@dataclass(frozen=True)
class _LaneScope:
    task_id: str
    write_paths: frozenset[str]
    read_paths: frozenset[str]


# -- Agent Hub inventory fetch --


def _owner_to_session(owner: dict[str, Any]) -> dict[str, object]:
    """Convert a live-ownership record to the normalized session shape."""

    def _lst(key: str) -> list:
        val = owner.get(key)
        return val if isinstance(val, list) else []

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
        "scope_paths": _lst("scope_paths"),
        "declared_scope_paths": _lst("declared_scope_paths"),
        "observed_read_paths": _lst("observed_read_paths"),
        "observed_write_paths": _lst("observed_write_paths"),
        "scope_confidence": owner.get("scope_confidence"),
        "created_at": owner.get("created_at"),
        "updated_at": owner.get("updated_at"),
    }


def _fetch_live_project_inventory(
    project_id: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return (owner_sessions, specialist_rows) for the given project."""
    headers = build_agent_hub_headers(default_request_source="summitflow-task-lane-preflight")
    with httpx.Client(timeout=_LIST_SESSIONS_TIMEOUT) as client:
        ownership_response = client.get(
            f"{AGENT_HUB_URL}{_LIVE_OWNERSHIP_PATH.format(project_id=project_id)}",
            headers=headers,
        )
        if ownership_response.status_code != 404:
            ownership_response.raise_for_status()
            payload = ownership_response.json()
            owners = payload.get("active_owners")
            specialists = payload.get("active_specialists")
            if isinstance(owners, list):
                owner_sessions = [_owner_to_session(o) for o in owners if isinstance(o, dict)]
                specialist_rows = [r for r in specialists if isinstance(r, dict)] if isinstance(specialists, list) else []
                return owner_sessions, specialist_rows
            sessions = payload.get("sessions")
            return (sessions, []) if isinstance(sessions, list) else ([], [])

        legacy_response = client.get(
            f"{AGENT_HUB_URL}{_LEGACY_SESSIONS_PATH}",
            headers=headers,
            params={"project_id": project_id, "status": "active", "page_size": 100},
        )
        legacy_response.raise_for_status()
        payload = legacy_response.json()
        sessions = payload.get("sessions", [])
        return (sessions if isinstance(sessions, list) else [], [])


# -- Specialist summarization --


def _summarize_active_specialists(
    rows: list[dict[str, object]],
) -> list[_SpecialistSummary]:
    """Group live specialist sessions for context surfaces without changing blockers."""
    counts: dict[str, int] = {}
    sources: dict[str, set[str]] = {}
    session_ids: dict[str, list[str]] = {}
    newest: dict[str, int] = {}
    oldest: dict[str, int] = {}

    for row in rows:
        slug = str(row.get("agent_slug") or "unknown")
        raw_age = row.get("age_minutes")
        age = int(raw_age) if isinstance(raw_age, (int, float)) else 0
        counts[slug] = counts.get(slug, 0) + 1
        if slug not in sources:
            sources[slug] = set()
            session_ids[slug] = []
            newest[slug] = age
            oldest[slug] = age
        if row.get("request_source"):
            sources[slug].add(str(row["request_source"]))
        if row.get("session_id"):
            session_ids[slug].append(str(row["session_id"]))
        newest[slug] = min(newest[slug], age)
        oldest[slug] = max(oldest[slug], age)

    result: list[_SpecialistSummary] = [
        {
            "agent_slug": slug,
            "count": counts[slug],
            "request_sources": sorted(sources[slug]),
            "session_ids": session_ids[slug][:3],
            "newest_age_minutes": newest[slug],
            "oldest_age_minutes": oldest[slug],
        }
        for slug in counts
    ]
    return sorted(result, key=lambda r: (-r["count"], r["agent_slug"]))


# -- Session metadata helpers --


def _is_live_lane_session(session: dict[str, object]) -> bool:
    if session.get("workstream_status") in _RETIRED_WORKSTREAMS:
        return False
    return bool(session.get("external_id") or session.get("current_branch"))


def _lane_task_id(session: dict[str, object]) -> str | None:
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
        lane_kind = "worktree" if bool(session.get("is_worktree")) else "repo"
        location = f"{lane_kind} {working_dir}"
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


# -- Scope helpers --


def _normalize_scope_values(values: object) -> frozenset[str]:
    if not isinstance(values, list):
        return frozenset()
    result: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            continue
        path = raw.strip()
        while path.startswith("./"):
            path = path[2:]
        if not path or path.startswith("/"):
            continue
        if "\\" in path or "//" in path or path.endswith("/"):
            continue
        parts = path.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            continue
        normalized = str(PurePosixPath(path))
        if normalized != "." and not normalized.endswith("/"):
            result.add(normalized)
    return frozenset(result)


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
        if isinstance(values, list):
            merged.update(_normalize_scope_values(values))
    if not saw_scope_field or not merged:
        return None
    return _TaskScope(task_id=task_id, paths=frozenset(sorted(merged)))


def _load_live_lane_scope(session: dict[str, object], task_id: str) -> _LaneScope | None:
    """Prefer live session scope, falling back to task spirit scope for managed lanes."""
    declared_paths = _normalize_scope_values(session.get("declared_scope_paths"))
    write_paths = declared_paths | _normalize_scope_values(session.get("observed_write_paths"))
    read_paths = _normalize_scope_values(session.get("observed_read_paths"))
    scope_paths = _normalize_scope_values(session.get("scope_paths"))
    scope_confidence = str(session.get("scope_confidence") or "unknown")

    if scope_paths:
        if scope_confidence == _SCOPE_CONFIDENCE_OBSERVED_READ and not write_paths:
            read_paths = read_paths | scope_paths
        elif not write_paths:
            write_paths = write_paths | scope_paths

    if not write_paths and not read_paths:
        fallback = _load_task_scope(task_id)
        if fallback is None:
            return None
        return _LaneScope(task_id=task_id, write_paths=fallback.paths, read_paths=frozenset())

    return _LaneScope(task_id=task_id, write_paths=write_paths, read_paths=read_paths)


# -- Conflict detection --


def _assign_owner(result: TaskLaneConflictCheck, session: dict[str, object]) -> None:
    """Populate owner fields on result from the given session."""
    result.owner_session_id = str(session.get("id") or "")
    branch = session.get("current_branch")
    result.owner_branch = branch if isinstance(branch, str) else None
    result.owner_location = _lane_summary(session)


def _apply_same_task_conflict(
    result: TaskLaneConflictCheck, task_id: str, project_id: str, sessions: list[dict[str, object]]
) -> None:
    session = sessions[0]
    _assign_owner(result, session)
    target_status = _task_status(task_id)
    if target_status in _TERMINAL_TASK_STATUSES:
        result.overlap_kind = _STALE_SAME_TASK
        result.disposition = _RECONCILE
        result.issues.append(
            f"Task status is {target_status} but it still has a leftover live lane: {_lane_summary(session)}"
        )
        result.suggestions.append(
            "Reconcile or retire the leftover same-task lane before redispatching or treating "
            "the task as cleanly closed."
        )
    elif _is_stale_lane_session(session):
        result.overlap_kind = _STALE_SAME_TASK
        result.disposition = _RECONCILE
        result.issues.append(f"Task already has a likely stale active lane: {_lane_summary(session)}")
        result.suggestions.append(
            f"Inspect the lane with `{_SESSIONS_INSPECT_CMD.format(project_id=project_id)}` "
            "and reconcile or retire it before queueing another execution."
        )
    else:
        result.overlap_kind = _SAME_TASK
        result.disposition = _BLOCK
        result.issues.append(f"Task already has an active lane: {_lane_summary(session)}")
        result.suggestions.append(
            "Wait for the active lane to finish or reconcile it before queueing another execution."
        )


def _apply_unscoped_conflict(
    result: TaskLaneConflictCheck,
    overlap_kind: str,
    display_id: str,
    project_id: str,
    lane_sessions: list[dict[str, object]],
    suggestion_prefix: str,
) -> None:
    """Handle both unscoped-target and unscoped-lane conflicts."""
    chosen = lane_sessions[0]
    chosen_task_id = _lane_task_id(chosen)
    _assign_owner(result, chosen)
    lane_preview = "; ".join(_lane_summary(s) for s in lane_sessions[:2])
    result.conflicting_tasks = [chosen_task_id] if chosen_task_id else []
    result.overlap_kind = overlap_kind
    result.disposition = _WARN
    result.issues.append(
        f"Another active coding lane exists in project {project_id} but lacks usable file scope: {display_id}"
    )
    if lane_preview:
        result.suggestions.append(f"Active lane details: {lane_preview}")
    result.suggestions.append(
        f"{suggestion_prefix}; keep the current project-level guard and finish, retire, "
        "or scope the active lane before dispatching another coding task."
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
    _assign_owner(result, owner_session)
    result.conflicting_tasks = [overlap_id]
    result.overlap_paths = overlaps
    result.disposition = _BLOCK
    preview = ", ".join(overlaps[:3])
    if is_pure_plumbing:
        result.overlap_kind = _SHARED_PLUMBING
        result.shared_plumbing = True
        result.issues.append(
            f"Another active coding lane is already modifying shared plumbing in project {project_id}: "
            f"{overlap_id} ({preview})"
        )
        result.suggestions.append(
            f"Shared-plumbing overlap with {overlap_id}: {preview}. "
            "Do not run parallel coding lanes in adapters/tooling/orchestration areas; finish or retire "
            "the active lane first."
        )
        return

    is_plumbing_overlap = any(
        p.startswith(prefix) for p in overlaps for prefix in _SHARED_PLUMBING_PREFIXES
    )
    if is_plumbing_overlap:
        result.overlap_kind = _SHARED_PLUMBING
        result.shared_plumbing = True
        result.issues.append(
            f"Another active coding lane overlaps shared plumbing files in project {project_id}: "
            f"{overlap_id} ({preview})"
        )
    else:
        result.overlap_kind = _EXACT_FILE
        result.issues.append(
            f"Another active coding lane overlaps exact files in project {project_id}: "
            f"{overlap_id} ({preview})"
        )
    result.suggestions.append(
        f"Exact-file overlap with {overlap_id}: {preview}. "
        "Finish or retire the active lane before dispatching another coding task."
    )


def _classify_lane_scopes(
    lane_sessions: list[dict[str, object]],
) -> tuple[list[tuple[str, _LaneScope]], list[str]]:
    """Partition lane sessions into (scoped list, unscoped_ids list)."""
    scoped: list[tuple[str, _LaneScope]] = []
    unscoped_ids: list[str] = []
    for session in lane_sessions:
        lane_id = _lane_task_id(session)
        scope = _load_live_lane_scope(session, lane_id) if lane_id else None
        if scope is None:
            unscoped_ids.append(lane_id or _UNKNOWN_TASK)
        else:
            scoped.append((lane_id or _UNKNOWN_TASK, scope))
    return scoped, unscoped_ids


def _find_scope_overlap(
    target_scope: _TaskScope,
    scoped: list[tuple[str, _LaneScope]],
) -> tuple[str | None, list[str], str | None]:
    """Return (overlap_id, overlap_paths, kind) for the highest-priority overlap: write > plumbing > read."""
    target_shared = sorted(
        p for p in target_scope.paths if any(p.startswith(pfx) for pfx in _SHARED_PLUMBING_PREFIXES)
    )
    read_id: str | None = None
    read_paths: list[str] = []
    for lane_id, scope in scoped:
        write_overlaps = sorted(target_scope.paths & scope.write_paths)
        if write_overlaps:
            return lane_id, write_overlaps, "exact"
        if target_shared:
            active_shared = sorted(
                p for p in scope.write_paths if any(p.startswith(pfx) for pfx in _SHARED_PLUMBING_PREFIXES)
            )
            if active_shared:
                return lane_id, sorted(set(target_shared) | set(active_shared)), "plumbing"
        if not read_paths:
            read_overlaps = sorted(target_scope.paths & scope.read_paths)
            if read_overlaps:
                read_id, read_paths = lane_id, read_overlaps
    return (read_id, read_paths, "read") if read_id else (None, [], None)


def _apply_scoped_conflict(
    result: TaskLaneConflictCheck,
    task_id: str,
    project_id: str,
    lane_sessions: list[dict[str, object]],
    target_scope: _TaskScope,
) -> None:
    scoped, unscoped_ids = _classify_lane_scopes(lane_sessions)
    overlap_id, overlap_paths, overlap_kind = _find_scope_overlap(target_scope, scoped)

    if overlap_kind == "read":
        assert overlap_id is not None
        chosen = next(s for s in lane_sessions if _lane_task_id(s) == overlap_id)
        _assign_owner(result, chosen)
        result.conflicting_tasks = [overlap_id]
        result.overlap_kind = _READ_OVERLAP
        result.overlap_paths = overlap_paths
        result.disposition = _WARN
        preview = ", ".join(overlap_paths[:3])
        result.issues.append(
            f"Another active coding lane is reading files in the target scope in project {project_id}: "
            f"{overlap_id} ({preview})"
        )
        result.suggestions.append(
            f"Read-scope overlap with {overlap_id}: {preview}. Coordinate before editing if that lane "
            "may promote into writes, but safe parallel work can continue."
        )
    elif overlap_id is not None:
        _apply_write_overlap_conflict(
            result, project_id, lane_sessions, overlap_id, overlap_paths, overlap_kind == "plumbing"
        )
    elif not scoped and unscoped_ids:
        chosen_id = sorted(unscoped_ids)[0]
        chosen_sessions = [s for s in lane_sessions if (_lane_task_id(s) or _UNKNOWN_TASK) == chosen_id]
        _apply_unscoped_conflict(
            result, _UNSCOPED_LANE, chosen_id, project_id, chosen_sessions or lane_sessions,
            "Active lane scope unavailable",
        )
    # else: at least one active lane is safely scoped and disjoint; allow.


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
        stale_session = stale_sessions[0]
        _assign_owner(result, stale_session)
        result.overlap_kind = _STALE_LANE
        result.disposition = _RECONCILE
        result.conflicting_tasks = [t for s in stale_sessions if (t := _lane_task_id(s))]
        preview = ", ".join(result.conflicting_tasks[:3])
        lane_preview = "; ".join(_lane_summary(s) for s in lane_sessions[:2])
        result.issues.append(
            f"Another likely stale active coding lane exists in project {project_id}: {preview}"
        )
        if lane_preview:
            result.suggestions.append(f"Active lane details: {lane_preview}")
        result.suggestions.append(
            f"Inspect the lane with `{_SESSIONS_INSPECT_CMD.format(project_id=project_id)}` "
            "and retire or reconcile it if the session is no longer truly live."
        )
        return

    target_scope = _load_task_scope(task_id)
    if target_scope is None:
        _apply_unscoped_conflict(
            result, _UNSCOPED_TARGET, task_id, project_id, lane_sessions,
            "Target task scope unavailable",
        )
        return

    _apply_scoped_conflict(result, task_id, project_id, lane_sessions, target_scope)


# -- Public API --


def check_task_lane_conflicts(task_id: str, project_id: str) -> TaskLaneConflictCheck:
    """Check whether active Agent Hub lanes conflict with autonomous dispatch."""
    try:
        sessions, specialists = _fetch_live_project_inventory(project_id)
    except Exception as e:
        logger.warning("task_lane_preflight_failed", task_id=task_id, project_id=project_id, error=str(e))
        return TaskLaneConflictCheck()

    # Partition sessions into same-task and other-active-task lanes
    same_task_sessions: list[dict[str, object]] = []
    other_lane_sessions: list[dict[str, object]] = []
    for session in sessions:
        if not _is_live_lane_session(session):
            continue
        lane_id = _lane_task_id(session)
        if lane_id == task_id:
            same_task_sessions.append(session)
        elif lane_id and _task_status(lane_id) not in _TERMINAL_TASK_STATUSES:
            other_lane_sessions.append(session)

    result = TaskLaneConflictCheck(active_specialists=_summarize_active_specialists(specialists))

    if same_task_sessions:
        _apply_same_task_conflict(result, task_id, project_id, same_task_sessions)

    if other_lane_sessions:
        _apply_other_lane_conflict(result, task_id, project_id, other_lane_sessions)

    return result
