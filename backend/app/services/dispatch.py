"""Task dispatch service.

Replaces Redis pub/sub dispatch with direct Hatchet workflow triggers.
Called from CLI (st autocode) and API endpoints to queue tasks for execution.
"""

from __future__ import annotations

from typing import Any

from ..logging_config import get_logger
from ..storage import tasks as task_store
from ..tasks.autonomous.pickup import _determine_next_stage

logger = get_logger(__name__)


async def dispatch_task(task_id: str, project_id: str) -> dict[str, Any]:
    """Dispatch a task for autonomous execution via Hatchet.

    Determines the appropriate pipeline stage using the canonical
    _determine_next_stage logic (checks task_spirit + subtasks), then
    triggers the corresponding Hatchet workflow.

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

    stage = _determine_next_stage(task_id)

    # Trigger appropriate Hatchet workflow
    from ..workflows.models import TaskInput

    task_input = TaskInput(task_id=task_id, project_id=project_id)

    if stage == "ideation":
        from ..workflows.pipeline import ideate_wf

        await ideate_wf.aio_run_no_wait(task_input)
    elif stage == "triage":
        from ..workflows.pipeline import triage_wf

        await triage_wf.aio_run_no_wait(task_input)
    elif stage == "planning":
        from ..workflows.pipeline import plan_wf

        await plan_wf.aio_run_no_wait(task_input)
    elif stage == "execution":
        from ..workflows.pipeline import execute_wf

        await execute_wf.aio_run_no_wait(task_input)
    else:
        logger.warning("Unknown stage, dispatching to triage", task_id=task_id, stage=stage)
        from ..workflows.pipeline import triage_wf

        await triage_wf.aio_run_no_wait(task_input)

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
