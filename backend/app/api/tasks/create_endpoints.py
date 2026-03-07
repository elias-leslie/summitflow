"""Tasks API - Create endpoints.

Handles create_task, batch_create_tasks, and create_task_from_ideation.
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
from ...services.task_execution_readiness import sync_task_execution_readiness
from ...services.task_second_opinion import ensure_second_opinion_tracking
from ...storage import tasks as task_store
from ...storage.tasks.execution_mode import EXECUTION_MODE_AUTONOMOUS, normalize_execution_fields
from .response import task_to_response

router = APIRouter()
logger = get_logger(__name__)


async def _save_spirit_fields(task_id: str, task: TaskCreate) -> None:
    """Persist spirit fields to task_spirit table if any are provided."""
    if not any([task.objective, task.spirit_anti, task.decisions, task.constraints, task.done_when]):
        return
    from ...storage.task_spirit import upsert_task_spirit

    await asyncio.to_thread(
        upsert_task_spirit,
        task_id=task_id,
        objective=task.objective or "",
        spirit_anti=task.spirit_anti,
        decisions=task.decisions,
        constraints=task.constraints,
        done_when=task.done_when,
        complexity=task.complexity,
    )


_SIMPLE_TASK_TYPES = {"bug", "debt", "regression", "refactor"}


def _auto_classify_complexity(task: dict) -> None:
    """Auto-classify complexity at creation if not already set.

    Rules:
    - Already set → respect it
    - task_type in (bug, debt, regression, refactor) → SIMPLE
    - objective AND done_when both present → STANDARD
    - Otherwise → None (untriaged)
    """
    if task.get("complexity"):
        return

    task_type = task.get("task_type", "task")
    if task_type in _SIMPLE_TASK_TYPES:
        task_store.update_task(task["id"], complexity="SIMPLE")
        return

    # Check if spirit fields suggest STANDARD
    task_id = task.get("id")
    if task_id:
        from ...storage.task_spirit import get_task_spirit

        spirit = get_task_spirit(task_id)
        if spirit and spirit.get("objective") and spirit.get("done_when"):
            task_store.update_task(task_id, complexity="STANDARD")


@router.post("/projects/{project_id}/tasks", response_model=TaskResponse)
async def create_task(project_id: str, task: TaskCreate) -> TaskResponse:
    """Create a new task. When auto_dispatch=True, queues and dispatches to Hatchet."""
    execution_fields = normalize_execution_fields(
        task_type=task.task_type,
        execution_mode=(
            EXECUTION_MODE_AUTONOMOUS
            if task.auto_dispatch
            else task.execution_mode
        ),
        autonomous=task.autonomous or task.auto_dispatch,
    )
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
        execution_mode=execution_fields["execution_mode"],
        autonomous=execution_fields["autonomous"],
        labels=task.labels,
        ai_review=task.ai_review,
    )

    await _save_spirit_fields(created["id"], task)
    _auto_classify_complexity(created)
    current = await asyncio.to_thread(task_store.get_task, created["id"])
    if current:
        created = current
    await asyncio.to_thread(
        ensure_second_opinion_tracking,
        created["id"],
        created,
        None,
        source="task-create",
    )
    await asyncio.to_thread(sync_task_execution_readiness, created["id"], "task-create")

    if task.auto_dispatch:
        await _dispatch_created_task(created["id"], project_id)
    updated = await asyncio.to_thread(task_store.get_task, created["id"])
    if updated:
        created = updated

    return task_to_response(created)


@router.post("/projects/{project_id}/tasks/from-ideation", response_model=IdeationTaskResponse)
async def create_task_from_ideation(
    project_id: str, body: IdeationTaskCreate
) -> IdeationTaskResponse:
    """Create a task from ideation agent output. Normalizes complexity to DB enum."""
    created = await asyncio.to_thread(
        task_store.create_task,
        project_id=project_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        task_type=body.task_type,
        complexity=body.to_db_complexity(),
        execution_mode=EXECUTION_MODE_AUTONOMOUS if body.auto_dispatch else None,
        autonomous=body.auto_dispatch,
        labels=body.labels,
    )

    task_id = created["id"]
    await asyncio.to_thread(
        ensure_second_opinion_tracking,
        task_id,
        created,
        None,
        source="ideation-create",
    )
    await asyncio.to_thread(sync_task_execution_readiness, task_id, "ideation-create")
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


async def _queue_task(task_id: str) -> None:
    """Update task status to 'queue', raising HTTPException on failure."""
    from ...storage.tasks.status import update_task_status

    try:
        await asyncio.to_thread(update_task_status, task_id, "queue")
    except ValueError as e:
        logger.error("ideation_task_queue_failed", task_id=task_id, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Task created (id={task_id}) but status update to queue failed: {e}",
        ) from None


async def _dispatch_created_task(task_id: str, project_id: str) -> str | None:
    """Queue task and dispatch to Hatchet pipeline. Returns stage or None."""
    from ...services.dispatch import dispatch_task

    await _queue_task(task_id)

    try:
        result = await dispatch_task(task_id, project_id)
        logger.info("ideation_task_dispatched", task_id=task_id, project_id=project_id, stage=result.get("stage"))
        return str(result.get("stage"))
    except ImportError:
        logger.debug("Hatchet workflows not available for dispatch", task_id=task_id)
        return None
    except ValueError as e:
        logger.error("ideation_task_dispatch_failed", task_id=task_id, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Task created and queued (id={task_id}) but Hatchet dispatch failed: {e}",
        ) from None
