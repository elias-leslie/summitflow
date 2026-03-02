"""Task dispatch service.

Replaces Redis pub/sub dispatch with direct Hatchet workflow triggers.
Called from CLI (st autocode) and API endpoints to queue tasks for execution.
"""

from __future__ import annotations

from typing import TypedDict

from ..logging_config import get_logger
from ..storage import tasks as task_store
from ..tasks.autonomous.pickup import _determine_next_stage

logger = get_logger(__name__)


class DispatchResult(TypedDict):
    task_id: str
    project_id: str
    stage: str
    status: str


async def _trigger_workflow(stage: str, task_id: str, project_id: str) -> None:
    """Trigger the appropriate Hatchet workflow for the given stage."""
    from ..workflows.models import TaskInput
    from ..workflows.pipeline import (
        execute_wf,
        ideate_wf,
        plan_wf,
        triage_wf,
    )

    task_input = TaskInput(task_id=task_id, project_id=project_id)

    workflow_map = {
        "ideation": ideate_wf,
        "triage": triage_wf,
        "planning": plan_wf,
        "execution": execute_wf,
    }

    workflow = workflow_map.get(stage)
    if workflow is None:
        logger.warning("Unknown stage, dispatching to triage", task_id=task_id, stage=stage)
        workflow = triage_wf

    await workflow.aio_run_no_wait(task_input)


async def dispatch_task(task_id: str, project_id: str) -> DispatchResult:
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

    await _trigger_workflow(stage, task_id, project_id)

    logger.info(
        "task_dispatched",
        task_id=task_id,
        project_id=project_id,
        stage=stage,
    )

    return DispatchResult(
        task_id=task_id,
        project_id=project_id,
        stage=stage,
        status="dispatched",
    )
