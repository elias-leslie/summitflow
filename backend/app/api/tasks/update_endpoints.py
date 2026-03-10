"""Tasks API - Update/delete/status endpoints.

Handles:
- update_task: Update task fields (splits updates between task and task_spirit tables)
- delete_task: Delete a task
- update_task_status: Update task status with completion gate validation
- execute_task: Queue task for autonomous execution
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from ...logging_config import get_logger
from ...schemas.tasks import TaskResponse, TaskStatusUpdate, TaskUpdate
from ...services.task_execution_readiness import sync_task_execution_readiness
from ...services.task_second_opinion import ensure_second_opinion_tracking
from ...services.task_validation import validate_task_ready
from ...storage import log_task_event
from ...storage import tasks as task_store
from ...storage.tasks.execution_mode import is_manual_only_mode
from .helpers import dispatch_autonomous_task, get_step_verification_status, verify_task_project
from .response import task_to_response

logger = get_logger(__name__)

router = APIRouter()


@router.patch("/projects/{project_id}/tasks/{task_id}", response_model=TaskResponse)
async def update_task(project_id: str, task_id: str, update: TaskUpdate) -> TaskResponse:
    """Update task fields (splits updates between task and task_spirit tables)."""
    from ...storage.task_spirit import update_task_spirit

    existing = await asyncio.to_thread(verify_task_project, task_id, project_id)

    update_fields = update.model_dump(exclude_unset=True)
    if not update_fields:
        return task_to_response(existing)

    # Split into task fields and spirit fields
    spirit_fields = {"objective", "spirit_anti", "decisions", "constraints", "done_when"}
    task_updates = {k: v for k, v in update_fields.items() if k not in spirit_fields}
    spirit_updates = {
        k: v for k, v in update_fields.items() if k in spirit_fields and k != "labels"
    }

    # Update task table
    if task_updates:
        updated = await asyncio.to_thread(task_store.update_task, task_id, **task_updates)
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to update task")
    else:
        updated = existing

    # Update task_spirit table
    if spirit_updates:
        await asyncio.to_thread(update_task_spirit, task_id, **spirit_updates)
    refreshed = await asyncio.to_thread(task_store.get_task, task_id)
    if refreshed:
        updated = refreshed
    await asyncio.to_thread(
        ensure_second_opinion_tracking,
        task_id,
        updated,
        None,
        source="task-update",
    )
    await asyncio.to_thread(sync_task_execution_readiness, task_id, "task-update")
    refreshed = await asyncio.to_thread(task_store.get_task, task_id)
    if refreshed:
        updated = refreshed

    return task_to_response(updated)


@router.delete("/projects/{project_id}/tasks/{task_id}", response_model=dict[str, Any])
async def delete_task(project_id: str, task_id: str) -> dict[str, Any]:
    """Delete a task."""
    await asyncio.to_thread(verify_task_project, task_id, project_id)

    deleted = await asyncio.to_thread(task_store.delete_task, task_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete task")

    return {
        "status": "deleted",
        "project_id": project_id,
        "task_id": task_id,
    }


async def _merge_step_verification(task_id: str, updated: dict[str, Any]) -> dict[str, Any] | None:
    """Merge step-level verification into verification_result on completion.

    Preserves existing keys (e.g. execution_clean from autocode pipeline).
    """
    step_status = await asyncio.to_thread(get_step_verification_status, task_id)
    existing = updated.get("verification_result") or {}
    merged = {
        **existing,
        "total": step_status["total"],
        "verified": step_status["verified"],
        "unverified": step_status["unverified"],
        "all_verified": step_status["all_verified"],
    }
    return await asyncio.to_thread(task_store.update_task, task_id, verification_result=merged)


@router.patch("/projects/{project_id}/tasks/{task_id}/status", response_model=TaskResponse)
async def update_task_status(
    project_id: str, task_id: str, update: TaskStatusUpdate
) -> TaskResponse:
    """Update task status with completion gate validation."""
    await asyncio.to_thread(verify_task_project, task_id, project_id)

    # Gate checks when completing
    # These gates ensure work is actually done before marking complete
    # skip_gates bypasses completion gate validation (e.g. autonomous pipeline)
    if update.status == "completed" and not update.skip_gates:
        from .crud_handlers import validate_completion_gates

        await validate_completion_gates(task_id)

    try:
        updated = await asyncio.to_thread(
            task_store.update_task_status,
            task_id,
            update.status,
            error_message=update.error_message,
            validate_transition=not (update.status == "completed" and update.skip_gates),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update task status")

    # Log completion reason to events if provided
    if update.reason and update.status in ("completed", "cancelled"):
        await asyncio.to_thread(log_task_event, task_id, f"Closed: {update.reason}")

    # Dispatch autonomous execution tasks on status transitions
    await dispatch_autonomous_task(task_id, update.status, project_id)

    if update.status == "completed" and updated:
        updated = await _merge_step_verification(task_id, updated)

    if updated is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task_to_response(updated)


@router.post("/projects/{project_id}/tasks/{task_id}/execute", response_model=TaskResponse)
async def execute_task(project_id: str, task_id: str) -> TaskResponse:
    """Queue task for autonomous execution."""
    existing = await asyncio.to_thread(verify_task_project, task_id, project_id)
    if is_manual_only_mode(existing.get("execution_mode")):
        raise HTTPException(
            status_code=400,
            detail="Task is manual-only and cannot be queued for autonomous execution",
        )
    readiness = await asyncio.to_thread(validate_task_ready, task_id, project_id)
    if not readiness.ready:
        readiness_detail: dict[str, Any] = {
            "issues": readiness.issues,
            "suggestions": readiness.suggestions,
        }
        if readiness.lane_conflict is not None:
            readiness_detail["lane_conflict"] = readiness.lane_conflict
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Task is not execution-ready for autonomous work",
                "details": [readiness_detail],
            },
        )

    try:
        updated = await asyncio.to_thread(task_store.update_task_status, task_id, "queue")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not updated:
        raise HTTPException(status_code=500, detail="Failed to start execution")

    # Dispatch autonomous execution
    await dispatch_autonomous_task(task_id, "queue", project_id)

    return task_to_response(updated)
