"""Workflow approval utilities.

Handle task plan approval logic.
"""

from __future__ import annotations

from typing import Any

from ...logging_config import get_logger
from ...storage import tasks as task_store
from ...storage.task_spirit import approve_plan, create_task_spirit

logger = get_logger(__name__)


def approve_task_plan_impl(task_id: str, approved_by: str, notes: str | None) -> dict[str, Any]:
    """Approve task plan, creating task_spirit if needed.

    Args:
        task_id: Task ID
        approved_by: User who approved the plan
        notes: Optional approval notes

    Returns:
        Approval result with plan_status, plan_approved_at, plan_approved_by

    Raises:
        RuntimeError: If approval fails
    """
    result = approve_plan(task_id, approved_by=approved_by, notes=notes)

    if not result:
        # Task exists but no task_spirit record - create one with approved status
        try:
            task_data = task_store.get_task(task_id)
            if task_data:
                create_task_spirit(
                    task_id=task_id,
                )
                result = approve_plan(task_id, approved_by=approved_by, notes=notes)
        except Exception as e:
            logger.warning("Failed to create task_spirit for approval: %s", e)

    if not result:
        raise RuntimeError(f"Failed to approve plan for task {task_id}")

    return result
