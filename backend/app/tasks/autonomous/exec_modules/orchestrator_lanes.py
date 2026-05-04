"""Same-task lane guard helpers for autonomous execution."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def session_ready_for_reclaim(
    session: dict[str, Any] | None,
    *,
    final_statuses: set[str],
    final_health: set[str],
    reapable_states: set[str],
) -> bool:
    if not isinstance(session, dict):
        return False
    if str(session.get("status") or "").strip().lower() in final_statuses:
        return True
    live_activity = session.get("live_activity")
    if not isinstance(live_activity, dict):
        return False
    if bool(live_activity.get("reapable")):
        return True
    lifecycle_state = str(live_activity.get("lifecycle_state") or "").strip().lower()
    if lifecycle_state in reapable_states:
        return True
    health = str(live_activity.get("health") or "").strip().lower()
    return health in final_health


def maybe_reclaim_same_task_lane(
    task_id: str,
    project_id: str,
    lane_check: Any,
    *,
    fetch_session: Callable[[str], dict[str, Any] | None],
    session_ready: Callable[[dict[str, Any] | None], bool],
    close_session: Callable[[str], bool],
    lane_conflicts: Callable[[str, str], Any],
    emit_log: Callable[..., None],
) -> tuple[Any, bool]:
    if lane_check.overlap_kind != "stale_same_task" or not lane_check.owner_session_id:
        return lane_check, False

    owner_session_id = str(lane_check.owner_session_id)
    session, error = _safe_fetch_session(owner_session_id, fetch_session)
    if error:
        _emit_reclaim_warning(task_id, project_id, str(error), emit_log)
        return lane_check, False

    if not session_ready(session):
        emit_log(
            task_id,
            "warn",
            f"Stale same-task session {owner_session_id} was not reclaimable on recheck",
            source="orchestrator",
            project_id=project_id,
        )
        return lane_check, False

    emit_log(
        task_id,
        "info",
        f"Reclaiming stale same-task session {owner_session_id}",
        source="orchestrator",
        project_id=project_id,
    )
    try:
        close_session(owner_session_id)
    except Exception as exc:
        emit_log(
            task_id,
            "warn",
            f"Failed to close stale same-task session {owner_session_id}: {type(exc).__name__}: {exc}",
            source="orchestrator",
            project_id=project_id,
        )
        return lane_check, False

    return lane_conflicts(task_id, project_id), True


def _safe_fetch_session(
    owner_session_id: str,
    fetch_session: Callable[[str], dict[str, Any] | None],
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return fetch_session(owner_session_id), None
    except Exception as exc:
        return None, f"Could not inspect stale same-task session {owner_session_id}: {type(exc).__name__}: {exc}"


def _emit_reclaim_warning(
    task_id: str,
    project_id: str,
    message: str,
    emit_log: Callable[..., None],
) -> None:
    emit_log(task_id, "warn", message, source="orchestrator", project_id=project_id)


def same_task_lane_guard_result(
    task_id: str,
    project_id: str,
    lane_check: Any,
    *,
    reclaimed: bool,
    emit_log: Callable[..., None],
    logger: Any,
) -> dict[str, Any] | None:
    if lane_check.overlap_kind == "stale_same_task":
        owner = lane_check.owner_session_id or "unknown"
        emit_log(
            task_id,
            "warn",
            f"Execution skipped: stale same-task session {owner} could not be reclaimed",
            project_id=project_id,
        )
        return {
            "task_id": task_id,
            "status": "already_running",
            "message": "Stale task session requires reconciliation",
            "owner_session_id": lane_check.owner_session_id,
        }
    if lane_check.overlap_kind != "same_task" or lane_check.disposition != "block":
        return None

    owner = lane_check.owner_session_id or "unknown"
    emit_log(
        task_id,
        "info",
        (
            f"Execution skipped: refreshed same-task session still active with owner {owner}"
            if reclaimed
            else f"Execution skipped: active task session already owned by session {owner}"
        ),
        project_id=project_id,
    )
    logger.info(
        "Skipping duplicate autonomous execution for active task session",
        task_id=task_id,
        project_id=project_id,
        owner_session_id=lane_check.owner_session_id,
        owner_location=lane_check.owner_location,
    )
    return {
        "task_id": task_id,
        "status": "already_running",
        "message": "Active task session already exists",
        "owner_session_id": lane_check.owner_session_id,
    }
