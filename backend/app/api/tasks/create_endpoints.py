"""Tasks API - Create endpoints.

Handles:
- create_task: Create a new task with optional spirit fields
- batch_create_tasks: Create multiple tasks with optional nested subtasks
- create_task_from_ideation: Create a task from ideation agent output with auto-dispatch
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from ...logging_config import get_logger
from ...schemas.tasks import (
    BatchTaskRequest,
    BatchTaskResponse,
    IdeationTaskCreate,
    IdeationTaskResponse,
    TaskCreate,
    TaskResponse,
)
from ...storage import tasks as task_store
from .response import task_to_response

router = APIRouter()
logger = get_logger(__name__)


@router.post("/projects/{project_id}/tasks", response_model=TaskResponse)
async def create_task(project_id: str, task: TaskCreate) -> TaskResponse:
    """Create a new task with optional spirit fields.

    When auto_dispatch=True, the task is automatically queued and dispatched
    to the Hatchet pipeline after creation (same as `st autocode`).
    """
    from ...storage.task_spirit import upsert_task_spirit

    created = await asyncio.to_thread(
        task_store.create_task,
        project_id=project_id,
        title=task.title,
        description=task.description,
        capability_id=task.capability_id,
        priority=task.priority,
        task_type=task.task_type,
        parent_task_id=task.parent_task_id,
        complexity=task.complexity,
        autonomous=task.autonomous or task.auto_dispatch,
        labels=task.labels,
    )

    # Save spirit fields to task_spirit table
    if task.objective or task.spirit_anti or task.decisions or task.constraints or task.done_when:
        await asyncio.to_thread(
            upsert_task_spirit,
            task_id=created["id"],
            objective=task.objective or "",
            spirit_anti=task.spirit_anti,
            decisions=task.decisions,
            constraints=task.constraints,
            done_when=task.done_when,
            complexity=task.complexity,
        )

    # Auto-dispatch to Hatchet pipeline if requested
    if task.auto_dispatch:
        await _dispatch_created_task(created["id"], project_id)
        # Re-fetch to get updated status
        updated = await asyncio.to_thread(task_store.get_task, created["id"])
        if updated:
            created = updated

    return task_to_response(created)


@router.post("/projects/{project_id}/tasks/from-ideation", response_model=IdeationTaskResponse)
async def create_task_from_ideation(
    project_id: str, body: IdeationTaskCreate
) -> IdeationTaskResponse:
    """Create a task from ideation agent output with optional auto-dispatch.

    Accepts the exact schema the ideation agent's create_task tool produces
    and handles creation + dispatch in one call.

    The ideation agent sends complexity as lowercase (simple/standard/complex);
    this endpoint normalizes it to the DB enum (SIMPLE/STANDARD/COMPLEX).
    """
    db_complexity = body.to_db_complexity()

    created = await asyncio.to_thread(
        task_store.create_task,
        project_id=project_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        task_type=body.task_type,
        complexity=db_complexity,
        autonomous=body.auto_dispatch,
        labels=body.labels,
    )

    task_id = created["id"]
    dispatched = False
    dispatch_stage: str | None = None

    if body.auto_dispatch:
        dispatch_stage = await _dispatch_created_task(task_id, project_id)
        dispatched = dispatch_stage is not None

    return IdeationTaskResponse(
        task_id=task_id,
        project_id=project_id,
        status="queue" if dispatched else "pending",
        dispatched=dispatched,
        dispatch_stage=dispatch_stage,
    )


@router.post("/projects/{project_id}/tasks/batch", response_model=BatchTaskResponse)
async def batch_create_tasks(project_id: str, body: BatchTaskRequest) -> BatchTaskResponse:
    """Create multiple tasks with optional nested subtasks. Handles partial failures."""
    from .crud_handlers import handle_batch_create_tasks

    return await handle_batch_create_tasks(project_id, body)


async def _dispatch_created_task(task_id: str, project_id: str) -> str | None:
    """Set task status to queue and dispatch to Hatchet pipeline.

    Follows the same logic as `st autocode` / the execute_task endpoint:
    1. Update status to "queue"
    2. Dispatch via Hatchet (determines stage: triage/planning/execution)

    Args:
        task_id: ID of the newly created task
        project_id: Project the task belongs to

    Returns:
        The pipeline stage dispatched to, or None if dispatch failed.
    """
    from ...services.dispatch import dispatch_task
    from ...storage.tasks.status import update_task_status

    try:
        await asyncio.to_thread(update_task_status, task_id, "queue")
    except ValueError as e:
        logger.error(
            "ideation_task_queue_failed",
            task_id=task_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Task created (id={task_id}) but status update to queue failed: {e}",
        ) from None

    try:
        result = await dispatch_task(task_id, project_id)
        logger.info(
            "ideation_task_dispatched",
            task_id=task_id,
            project_id=project_id,
            stage=result.get("stage"),
        )
        return str(result.get("stage"))
    except ImportError:
        logger.debug("Hatchet workflows not available for dispatch", task_id=task_id)
        return None
    except ValueError as e:
        logger.error(
            "ideation_task_dispatch_failed",
            task_id=task_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Task created and queued (id={task_id}) but Hatchet dispatch failed: {e}",
        ) from None
