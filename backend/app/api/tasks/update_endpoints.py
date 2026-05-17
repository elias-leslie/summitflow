"""Tasks API - Update/delete/status endpoints.

Handles:
- update_task: Update task fields (splits updates between task and task_spirit tables)
- delete_task: Delete a task
- update_task_status: Update task status with completion gate validation
- execute_task: Queue task for autonomous execution
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException

from ...logging_config import get_logger
from ...schemas.tasks import TaskResponse, TaskStatusUpdate, TaskUpdate
from ...services.dispatch import dispatch_task
from ...services.task_validation import validate_task_ready
from ...storage import log_task_event
from ...storage import tasks as task_store
from ...storage.tasks.execution_mode import EXECUTION_MODE_AUTONOMOUS, is_manual_only_mode
from ...tasks.autonomous.pickup_guards import validate_autonomous_dispatch
from .helpers import (
    dispatch_autonomous_task,
    refresh_task_tracking,
    verify_task_project,
)
from .response import task_to_response

logger = get_logger(__name__)

router = APIRouter()

_DEFERRED_DISPATCH_STATUSES = {"concurrency_limit", "concurrency_unavailable"}


def _dispatch_failure_status_code(status: str) -> int:
    """Map dispatch guard failures to API status codes."""
    if status == "unhealthy" or status == "disabled":
        return 503
    if status in {"not_claimable", "already_running"}:
        return 409
    return 409


def _raise_dispatch_failure(dispatch_result: Mapping[str, Any]) -> NoReturn:
    status = str(dispatch_result.get("status") or "blocked")
    raise HTTPException(
        status_code=_dispatch_failure_status_code(status),
        detail={
            "message": "Failed to start autonomous execution",
            "dispatch": dict(dispatch_result),
        },
    )


def _is_deferred_dispatch(dispatch_result: Mapping[str, Any]) -> bool:
    return str(dispatch_result.get("status") or "") in _DEFERRED_DISPATCH_STATUSES


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


async def _merge_step_verification(task_id: str, updated: dict[str, Any]) -> dict[str, Any] | None:
    """Merge step-level verification into verification_result on completion.

    Preserves existing keys (e.g. execution_clean from autocode pipeline).
    Steps layer has been removed, so step counts are always zero/empty.
    """
    existing = updated.get("verification_result") or {}
    merged = {
        **existing,
        "total": 0,
        "verified": 0,
        "unverified": [],
        "all_verified": True,
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

    # Log explicit lifecycle reasons to events when provided.
    if update.reason and update.status in ("completed", "cancelled", "paused", "pending"):
        verb = {"paused": "Paused", "pending": "Reopened"}.get(update.status, "Closed")
        await asyncio.to_thread(log_task_event, task_id, f"{verb}: {update.reason}")

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
    if existing.get("status") == "running":
        _raise_dispatch_failure(
            {
                "task_id": task_id,
                "project_id": project_id,
                "stage": "blocked",
                "status": "already_running",
                "reason": "task_already_running",
            }
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

    task_type = str(existing.get("task_type") or "").strip() or None
    guard_error = await asyncio.to_thread(
        validate_autonomous_dispatch,
        project_id,
        task_type,
        require_enabled=False,
        skip_concurrency=True,
    )
    if guard_error:
        status = str(guard_error.get("status") or "blocked")
        reason = str(guard_error.get("reason") or status)
        _raise_dispatch_failure(
            {
                "task_id": task_id,
                "project_id": project_id,
                "stage": "blocked",
                "status": status,
                "reason": reason,
                "details": guard_error,
            }
        )

    try:
        updated = await asyncio.to_thread(task_store.update_task_status, task_id, "pending")
        updated = await asyncio.to_thread(
            task_store.update_task,
            task_id,
            execution_mode=EXECUTION_MODE_AUTONOMOUS,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not updated:
        raise HTTPException(status_code=500, detail="Failed to queue execution")

    dispatch_result = await dispatch_task(task_id, project_id, manual_dispatch=True)
    if dispatch_result.get("status") != "dispatched" and not _is_deferred_dispatch(dispatch_result):
        _raise_dispatch_failure(dispatch_result)

    return task_to_response(updated)
