"""Task dispatch service.

Replaces Redis pub/sub dispatch with direct Hatchet workflow triggers.
Called from CLI (st autocode) and API endpoints to queue tasks for execution.
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict
from uuid import uuid4

from ..logging_config import get_logger
from ..storage import tasks as task_store
from ..storage.tasks.claims import claim_task, release_task
from ..tasks.autonomous.pickup import _determine_next_stage
from ..tasks.autonomous.pickup_guards import validate_autonomous_dispatch

logger = get_logger(__name__)


class DispatchResult(TypedDict):
    task_id: str
    project_id: str
    stage: str
    status: str
    reason: NotRequired[str]
    details: NotRequired[dict[str, Any]]


async def _trigger_workflow(stage: str, task_id: str, project_id: str, *, manual_dispatch: bool = False) -> None:
    """Trigger the appropriate Hatchet workflow for the given stage."""
    from ..workflows.models import TaskInput
    from ..workflows.pipeline import (
        critique_wf,
        execute_wf,
        ideate_wf,
        plan_wf,
        review_wf,
        triage_wf,
    )

    task_input = TaskInput(task_id=task_id, project_id=project_id, manual_dispatch=manual_dispatch)

    workflow_map = {
        "ideation": ideate_wf,
        "triage": triage_wf,
        "planning": plan_wf,
        "critique": critique_wf,
        "execution": execute_wf,
        "review": review_wf,
    }

    workflow = workflow_map.get(stage)
    if workflow is None:
        logger.warning("Skipping dispatch — unknown stage", task_id=task_id, stage=stage)
        return

    await workflow.aio_run_no_wait(task_input)


async def dispatch_task(task_id: str, project_id: str, *, manual_dispatch: bool = False) -> DispatchResult:
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

    task_type = str(task.get("task_type") or "").strip() or None
    if guard_error := validate_autonomous_dispatch(project_id, task_type, require_enabled=not manual_dispatch):
        status = str(guard_error.get("status") or "blocked")
        reason = str(guard_error.get("reason") or status)
        logger.warning(
            "Task dispatch blocked by autonomous guard",
            task_id=task_id,
            project_id=project_id,
            status=status,
            reason=reason,
        )
        return DispatchResult(
            task_id=task_id,
            project_id=project_id,
            stage="blocked",
            status=status,
            reason=reason,
            details=guard_error,
        )

    stage = _determine_next_stage(task_id)

    # Claim before execution to match batch-pickup path behavior
    claimed_for_execution = False
    dispatch_worker_id: str | None = None
    if stage == "execution":
        dispatch_worker_id = f"api-dispatch-{project_id}-{uuid4().hex[:12]}"
        claimed = claim_task(task_id, dispatch_worker_id, lock_duration_minutes=60)
        if not claimed:
            logger.warning("Task not claimable for execution", task_id=task_id)
            return DispatchResult(
                task_id=task_id,
                project_id=project_id,
                stage=stage,
                status="not_claimable",
            )
        claimed_for_execution = True

    try:
        await _trigger_workflow(stage, task_id, project_id, manual_dispatch=manual_dispatch)
    except Exception:
        if claimed_for_execution and dispatch_worker_id is not None:
            try:
                released = release_task(
                    task_id,
                    expected_worker_id=dispatch_worker_id,
                )
            except Exception:
                logger.exception(
                    "task_dispatch_claim_release_failed",
                    task_id=task_id,
                    project_id=project_id,
                    stage=stage,
                    worker_id=dispatch_worker_id,
                )
            else:
                logger.exception(
                    "task_dispatch_claim_release_result",
                    task_id=task_id,
                    project_id=project_id,
                    stage=stage,
                    worker_id=dispatch_worker_id,
                    released=released is not None,
                )
        raise

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
