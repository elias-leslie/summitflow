"""Database queries and stage routing for autonomous task pickup.

Provides read-only queries to find tasks ready for autonomous processing,
and logic to determine which pipeline stage a task needs next.
"""

from __future__ import annotations

from typing import Any

from app.services.task_execution_readiness import load_task_execution_readiness
from app.storage import tasks as task_store
from app.storage.agent_configs_autonomous import get_allowed_external_origins
from app.storage.connection import get_cursor
from app.storage.subtasks import get_subtasks_for_task
from app.storage.task_spirit import get_task_spirit

_PLANNING_FIELDS = frozenset({"description", "done_when", "subtasks"})


def _is_auto_generated(task: dict[str, Any]) -> bool:
    return "auto-generated" in (task.get("labels") or [])


def determine_next_stage(task_id: str) -> str:
    """Determine which pipeline stage a queued task needs.

    Returns:
        Stage name: 'ideation', 'triage', 'planning', 'execution', 'review', or 'unknown'
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

    if not subtasks and _is_auto_generated(task):
        return "execution"

    if not subtasks:
        return "planning"

    readiness = load_task_execution_readiness(task_id)
    if not readiness.ready:
        if _PLANNING_FIELDS.intersection(readiness.missing_fields):
            return "planning"
        return "execution"

    if any(not s.get("passes") for s in subtasks):
        return "execution"

    if task.get("status") == "pending":
        return "review"

    return "unknown"


def get_queued_autonomous_tasks(project_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Get pending autonomous tasks ready for pickup.

    Args:
        project_id: Project ID to filter by
        limit: Max tasks to return

    Returns:
        List of task dicts with id, title, task_type, complexity, status
    """
    allowed_origins = get_allowed_external_origins(project_id)
    origin_clause = ""
    params: list[Any] = [project_id]
    if allowed_origins is not None:
        origin_clause = "AND EXISTS (SELECT 1 FROM task_external_requests ter WHERE ter.task_id = tasks.id AND ter.external_origin = ANY(%s))"
        params.append(allowed_origins)
    params.append(limit)
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, title, task_type, complexity, status,
                   (SELECT ter.external_origin FROM task_external_requests ter
                    WHERE ter.task_id = tasks.id ORDER BY ter.external_origin LIMIT 1)
            FROM tasks
            WHERE project_id = %s
              AND status = 'pending'
              AND COALESCE(verification_result->'closeout'->>'state', '') <> 'pending'
              AND execution_mode = 'autonomous'
              {origin_clause}
              AND (claimed_by IS NULL OR lock_expires_at < NOW())
            ORDER BY
                priority ASC,
                CASE WHEN 'feedback' = ANY(labels) THEN 0 ELSE 1 END,
                created_at ASC
            LIMIT %s
            """,
            tuple(params),
        )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "title": row[1],
            "task_type": row[2],
            "complexity": row[3],
            "status": row[4],
            "external_origin": row[5] if len(row) > 5 else None,
        }
        for row in rows
    ]
