"""Task dispatch service.

Replaces Redis pub/sub dispatch with direct Hatchet workflow triggers.
Called from CLI (st autocode) and API endpoints to queue tasks for execution.
"""

from __future__ import annotations

from typing import Any

from ..logging_config import get_logger
from ..storage import tasks as task_store

logger = get_logger(__name__)


async def dispatch_task(task_id: str, project_id: str) -> dict[str, Any]:
    """Dispatch a task for autonomous execution via Hatchet.

    Validates task state and triggers the appropriate pipeline stage.

    Args:
        task_id: Task to dispatch
        project_id: Project the task belongs to

    Returns:
        Dict with dispatch status and details

    Raises:
        ValueError: If task is in invalid state for dispatch
    """
    task = task_store.get_task(task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")

    # Determine pipeline stage based on task state
    has_plan = bool(task.get("plan_content"))
    task_type = task.get("task_type", "task")

    if task_type == "idea" and not has_plan:
        stage = "triage"
    elif not has_plan:
        stage = "plan"
    else:
        stage = "execute"

    # Trigger appropriate Hatchet workflow
    from ..workflows.models import TaskInput

    task_input = TaskInput(task_id=task_id, project_id=project_id)

    if stage == "triage":
        from ..workflows.pipeline import triage_wf

        await triage_wf.aio_run_no_wait(task_input)
    elif stage == "plan":
        from ..workflows.pipeline import plan_wf

        await plan_wf.aio_run_no_wait(task_input)
    else:
        from ..workflows.pipeline import execute_wf

        await execute_wf.aio_run_no_wait(task_input)

    logger.info(
        "task_dispatched",
        task_id=task_id,
        project_id=project_id,
        stage=stage,
    )

    return {
        "task_id": task_id,
        "project_id": project_id,
        "stage": stage,
        "status": "dispatched",
    }
