"""Tasks API - Update/delete/status endpoints.

Handles:
- update_task: Update task fields (splits updates between task and task_spirit tables)
- delete_task: Delete a task
- update_task_status: Update task status with completion gate validation
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from ...logging_config import get_logger
from ...schemas.tasks import TaskResponse, TaskStatusUpdate, TaskUpdate
from ...storage import log_task_event
from ...storage import tasks as task_store
from .helpers import refresh_task_tracking, verify_task_project
from .response import task_to_response

logger = get_logger(__name__)

router = APIRouter()


@router.patch("/projects/{project_id}/tasks/{task_id}", response_model=TaskResponse)
async def update_task(project_id: str, task_id: str, update: TaskUpdate) -> TaskResponse:
    """Update task fields (splits updates between task and task_spirit tables)."""
    from ...services.task_plan_context import build_task_plan_context
    from ...storage.task_spirit import get_task_spirit, update_task_spirit, upsert_task_spirit

    existing = await asyncio.to_thread(verify_task_project, task_id, project_id)

    update_fields = update.model_dump(exclude_unset=True)
    if not update_fields:
        return task_to_response(existing)

    # Split into task fields and spirit fields.
    # Rich task-plan metadata now lives in task_spirit.context for round-trip fidelity.
    spirit_fields = {
        "done_when",
        "objective",
        "spirit_anti",
        "decisions",
        "constraints",
        "risks",
        "files_to_create",
        "files_to_modify",
        "references",
        "testing_strategy",
        "second_opinion",
        "execution_contract",
        "subtasks",
    }
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
        existing_spirit = await asyncio.to_thread(get_task_spirit, task_id)
        existing_context = existing_spirit.get("context") if existing_spirit else None
        merged_context: dict[str, Any] = (
            dict(existing_context) if isinstance(existing_context, dict) else {}
        )
        merged_context.update(build_task_plan_context(spirit_updates))
        spirit_payload: dict[str, Any] = {}
        if "done_when" in spirit_updates:
            spirit_payload["done_when"] = spirit_updates["done_when"]
        if merged_context:
            spirit_payload["context"] = merged_context

        if existing_spirit:
            await asyncio.to_thread(update_task_spirit, task_id, **spirit_payload)
        else:
            await asyncio.to_thread(upsert_task_spirit, task_id=task_id, **spirit_payload)
    updated = await refresh_task_tracking(task_id, "task-update")

    return task_to_response(updated)


@router.delete("/projects/{project_id}/tasks/{task_id}", response_model=dict[str, Any])
async def delete_task(project_id: str, task_id: str) -> dict[str, Any]:
    """Delete a task."""
    await asyncio.to_thread(verify_task_project, task_id, project_id)

    deleted = await asyncio.to_thread(
        task_store.delete_task,
        task_id,
        deletion_source="api:tasks.delete_task",
    )
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete task")

    return {
        "status": "deleted",
        "project_id": project_id,
        "task_id": task_id,
    }


@router.patch("/projects/{project_id}/tasks/{task_id}/status", response_model=TaskResponse)
async def update_task_status(
    project_id: str, task_id: str, update: TaskStatusUpdate
) -> TaskResponse:
    """Update task status with completion gate validation."""
    await asyncio.to_thread(verify_task_project, task_id, project_id)

    # Gate checks when completing
    # These gates ensure work is actually done before marking complete
    # skip_gates bypasses completion gate validation
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

    # Log explicit lifecycle reasons to events when provided.
    if update.reason and update.status in ("completed", "cancelled", "paused", "pending"):
        verb = {"paused": "Paused", "pending": "Reopened"}.get(update.status, "Closed")
        await asyncio.to_thread(log_task_event, task_id, f"{verb}: {update.reason}")

    if updated is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task_to_response(updated)
