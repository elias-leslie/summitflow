"""Archive stale auto-generated tasks left by the retired task generator."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.storage import log_task_event
from app.storage import tasks as task_store

from ..logging_config import get_logger

logger = get_logger(__name__)

OBSOLETE_WORKED_GRACE_HOURS = 24


def _has_work(task: dict[str, Any]) -> bool:
    commits = task.get("commits") or []
    return bool(
        task.get("started_at")
        or int(task.get("total_sessions") or 0) > 0
        or (isinstance(commits, list) and commits)
    )


def _is_dormant(task: dict[str, Any], *, grace_hours: int, now: datetime | None = None) -> bool:
    updated_at = task.get("updated_at")
    if not isinstance(updated_at, datetime):
        return True
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) - updated_at >= timedelta(hours=grace_hours)


def close_obsolete_generated_task(
    task: dict[str, Any],
    *,
    reason: str,
    resolved: bool,
    deletion_source: str,
    grace_hours: int = OBSOLETE_WORKED_GRACE_HOURS,
) -> str:
    """Delete unworked generated rows; complete/cancel worked dormant rows."""
    task_id = str(task.get("id") or "")
    if not task_id:
        return "skipped"
    if not _has_work(task):
        deleted = task_store.delete_task(
            task_id,
            deletion_source=deletion_source,
            deletion_reason=reason,
        )
        return "deleted" if deleted else "skipped"
    if not _is_dormant(task, grace_hours=grace_hours):
        return "skipped_active"
    status = "completed" if resolved else "cancelled"
    updated = task_store.update_task_status(
        task_id,
        status,
        error_message=reason,
        validate_transition=False,
    )
    if not updated:
        return "skipped"
    log_task_event(task_id, f"Auto-closed obsolete generated task: {reason}", source="routine_upkeep")
    return status


def _cancel_stale_task(task: dict[str, Any], max_age_days: int) -> bool:
    """Close a single stale generated task. Returns True if closed, False if skipped."""
    task_id = task.get("id")
    if not task_id:
        return False

    try:
        result = close_obsolete_generated_task(
            task,
            reason=f"No activity for {max_age_days}+ days",
            resolved=False,
            deletion_source="routine-upkeep:stale-generated-cleanup",
            grace_hours=max_age_days * 24,
        )
        if result in {"cancelled", "completed"}:
            log_task_event(
                task_id,
                f"Auto-cancelled: No activity for {max_age_days}+ days. "
                "Stale auto-generated task archived.",
            )
        logger.info("Closed stale task %s result=%s title=%s", task_id, result, task.get('title', '')[:50])
        return result in {"deleted", "cancelled", "completed"}
    except Exception:
        logger.exception("Failed to cancel task %s", task_id)
        return False


def cleanup_stale_tasks(max_age_days: int = 30) -> dict[str, Any]:
    """Archive auto-generated tasks that have been pending without activity."""
    from app.storage.tasks import get_stale_tasks

    try:
        stale_tasks = get_stale_tasks(max_age_days=max_age_days, limit=100)
        cancelled = sum(
            1 for task in stale_tasks if _cancel_stale_task(task, max_age_days)
        )
        skipped = len(stale_tasks) - cancelled

        logger.info("Stale task cleanup complete: cancelled=%d, skipped=%d", cancelled, skipped)
        return {
            "cancelled_count": cancelled,
            "skipped_count": skipped,
            "max_age_days": max_age_days,
        }
    except Exception as e:
        logger.error("Error in stale task cleanup: %s", e)
        return {"error": str(e), "cancelled_count": 0, "skipped_count": 0}
