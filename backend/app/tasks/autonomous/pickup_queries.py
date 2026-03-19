"""Database queries and stage routing for autonomous task pickup.

Provides read-only queries to find tasks ready for autonomous processing,
and logic to determine which pipeline stage a task needs next.
"""

from __future__ import annotations

from typing import Any

from app.services.task_execution_readiness import load_task_execution_readiness
from app.storage import tasks as task_store
from app.storage.connection import get_connection
from app.storage.subtasks import get_subtasks_for_task
from app.storage.task_spirit import get_task_spirit

_REPLANNING_FIELDS = frozenset(
    {"description", "done_when", "subtasks", "context"}
)


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
        return "planning"

    readiness = load_task_execution_readiness(task_id)
    if not readiness.ready:
        if _REPLANNING_FIELDS.intersection(readiness.missing_fields):
            return "planning"
        return "unknown"

    if any(not s.get("passes") for s in subtasks):
        return "execution"

    return "unknown"


def get_queued_autonomous_tasks(project_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Get autonomous tasks in queue status ready for pickup.

    Args:
        project_id: Project ID to filter by
        limit: Max tasks to return

    Returns:
        List of task dicts with id, title, task_type, complexity, status
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, title, task_type, complexity, status
            FROM tasks
            WHERE project_id = %s
              AND status = 'queue'
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
