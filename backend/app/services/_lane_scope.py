"""Scope loading, normalization, and overlap detection for task-session preflight."""

from __future__ import annotations

from dataclasses import dataclass

from ..storage.task_spirit import get_task_spirit
from ._scope_paths import normalize_scope_values

_SHARED_PLUMBING_PREFIXES = (
    "backend/app/adapters/",
    "backend/app/api/complete/",
    "backend/app/services/tools/",
)


@dataclass(frozen=True)
class TaskScope:
    task_id: str
    paths: frozenset[str]


@dataclass(frozen=True)
class LaneScope:
    task_id: str
    write_paths: frozenset[str]
    read_paths: frozenset[str]


# Scope confidence literal
_SCOPE_CONFIDENCE_OBSERVED_READ = "observed_read"
_UNKNOWN_TASK = "unknown task"


def load_task_scope(task_id: str) -> TaskScope | None:
    """Load task scope from the task spirit context."""
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
            merged.update(normalize_scope_values(values))
    if not saw_scope_field or not merged:
        return None
    return TaskScope(task_id=task_id, paths=frozenset(sorted(merged)))


def load_live_lane_scope(session: dict[str, object], task_id: str | None) -> LaneScope | None:
    """Prefer live session scope, falling back to task spirit scope for managed sessions."""
    declared_paths = normalize_scope_values(session.get("declared_scope_paths"))
    write_paths = declared_paths | normalize_scope_values(session.get("observed_write_paths"))
    read_paths = normalize_scope_values(session.get("observed_read_paths"))
    scope_paths = normalize_scope_values(session.get("scope_paths"))
    scope_confidence = str(session.get("scope_confidence") or "unknown")

    if scope_paths:
        if scope_confidence == _SCOPE_CONFIDENCE_OBSERVED_READ and not write_paths:
            read_paths = read_paths | scope_paths
        elif not write_paths:
            write_paths = write_paths | scope_paths

    if not write_paths and not read_paths:
        if not task_id:
            return None
        fallback = load_task_scope(task_id)
        if fallback is None:
            return None
        return LaneScope(task_id=task_id, write_paths=fallback.paths, read_paths=frozenset())

    return LaneScope(task_id=task_id or _UNKNOWN_TASK, write_paths=write_paths, read_paths=read_paths)


def classify_lane_scopes(
    lane_sessions: list[dict[str, object]],
    lane_task_id_fn,
) -> tuple[list[tuple[str, LaneScope]], list[str]]:
    """Partition lane sessions into (scoped list, unscoped_ids list)."""
    scoped: list[tuple[str, LaneScope]] = []
    unscoped_ids: list[str] = []
    for session in lane_sessions:
        lane_id = lane_task_id_fn(session)
        scope = load_live_lane_scope(session, lane_id) if lane_id else None
        if scope is None:
            unscoped_ids.append(lane_id or _UNKNOWN_TASK)
        else:
            scoped.append((lane_id or _UNKNOWN_TASK, scope))
    return scoped, unscoped_ids


def find_scope_overlap(
    target_scope: TaskScope,
    scoped: list[tuple[str, LaneScope]],
) -> tuple[str | None, list[str], str | None]:
    """Return (overlap_id, overlap_paths, kind) for write overlap only."""
    target_shared = sorted(
        p for p in target_scope.paths if any(p.startswith(pfx) for pfx in _SHARED_PLUMBING_PREFIXES)
    )

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

    return None, [], None
