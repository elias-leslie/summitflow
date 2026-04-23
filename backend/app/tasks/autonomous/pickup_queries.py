"""Database queries and stage routing for autonomous task pickup.

Provides read-only queries to find tasks ready for autonomous processing,
and logic to determine which pipeline stage a task needs next.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.task_execution_readiness import load_task_execution_readiness
from app.services.task_planning_signature import build_task_planning_signature
from app.services.task_second_opinion import get_second_opinion_entry
from app.storage import tasks as task_store
from app.storage.connection import get_cursor
from app.storage.subtasks import get_subtasks_for_task
from app.storage.task_spirit import get_task_spirit

_REPLANNING_FIELDS = frozenset({"description", "done_when", "subtasks", "context", "execution_contract"})
_ADVISORY_MISSING_FIELDS = frozenset({"second_opinion"})


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _has_saved_plan_artifacts(
    spirit: dict[str, Any] | None,
    subtasks: list[dict[str, Any]],
) -> bool:
    if subtasks:
        return True
    if not isinstance(spirit, dict):
        return False
    if spirit.get("done_when"):
        return True
    context = spirit.get("context")
    if isinstance(context, dict):
        planned_subtasks = context.get("subtasks")
        if isinstance(planned_subtasks, list) and planned_subtasks:
            return True
    return False


def _latest_plan_timestamp(
    spirit: dict[str, Any] | None,
    subtasks: list[dict[str, Any]],
) -> datetime | None:
    timestamps = [
        timestamp
        for timestamp in (
            _parse_timestamp((spirit or {}).get("updated_at")),
            _parse_timestamp((spirit or {}).get("created_at")),
            *(_parse_timestamp(subtask.get("created_at")) for subtask in subtasks),
        )
        if timestamp is not None
    ]
    return max(timestamps) if timestamps else None


def _stored_plan_signature(spirit: dict[str, Any] | None) -> str | None:
    if not isinstance(spirit, dict):
        return None
    context = spirit.get("context")
    if not isinstance(context, dict):
        return None
    value = context.get("planning_signature")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _second_opinion_status(spirit: dict[str, Any] | None) -> str:
    entry = get_second_opinion_entry(spirit)
    status = str(entry.get("status") or "").strip().lower()
    return status


def _should_replan(
    task: dict[str, Any],
    spirit: dict[str, Any] | None,
    subtasks: list[dict[str, Any]],
    missing_fields: list[str],
) -> bool:
    if not _REPLANNING_FIELDS.intersection(missing_fields):
        return False
    if not _has_saved_plan_artifacts(spirit, subtasks):
        return True
    current_signature = build_task_planning_signature(task)
    stored_signature = _stored_plan_signature(spirit)
    if current_signature and stored_signature:
        return current_signature != stored_signature
    task_updated_at = _parse_timestamp(task.get("updated_at")) or _parse_timestamp(task.get("created_at"))
    planned_at = _latest_plan_timestamp(spirit, subtasks)
    if task_updated_at is None or planned_at is None:
        return True
    return task_updated_at > planned_at


def determine_next_stage(task_id: str) -> str:
    """Determine which pipeline stage a queued task needs.

    Returns:
        Stage name: 'ideation', 'triage', 'planning', 'execution', or 'unknown'
    """
    task = task_store.get_task(task_id)
    if not task:
        return "unknown"
    spirit = get_task_spirit(task_id)
    subtasks = get_subtasks_for_task(task_id)

    is_crowdsourced = "crowdsourced" in (task.get("labels") or [])
    if is_crowdsourced and (not spirit or not task.get("description")):
        return "ideation"

    if not spirit or not task.get("description"):
        return "triage"

    if not subtasks:
        if _has_saved_plan_artifacts(spirit, subtasks) and not _should_replan(
            task,
            spirit,
            subtasks,
            ["subtasks"],
        ):
            return "unknown"
        return "planning"

    readiness = load_task_execution_readiness(task_id)
    if not readiness.ready:
        second_opinion_status = _second_opinion_status(spirit)
        blocking_missing_fields = [
            field for field in readiness.missing_fields if field not in _ADVISORY_MISSING_FIELDS
        ]
        if _should_replan(task, spirit, subtasks, blocking_missing_fields):
            return "planning"
        if not blocking_missing_fields and second_opinion_status in {"pending", "needs_revision", ""}:
            return "execution"
        return "unknown"

    if any(not s.get("passes") for s in subtasks):
        return "execution"

    return "unknown"


def get_queued_autonomous_tasks(project_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Get pending autonomous tasks ready for pickup.

    Args:
        project_id: Project ID to filter by
        limit: Max tasks to return

    Returns:
        List of task dicts with id, title, task_type, complexity, status
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, title, task_type, complexity, status
            FROM tasks
            WHERE project_id = %s
              AND status = 'pending'
              AND execution_mode = 'autonomous'
              AND (claimed_by IS NULL OR lock_expires_at < NOW())
            ORDER BY priority ASC, created_at ASC
            LIMIT %s
            """,
            (project_id, limit),
        )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "title": row[1],
            "task_type": row[2],
            "complexity": row[3],
            "status": row[4],
        }
        for row in rows
    ]
