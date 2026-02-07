"""Tasks API - Core CRUD operations.

Handles:
- list_tasks, list_ready_tasks, list_blocked_tasks
- create_task, batch_create_tasks
- get_task, get_task_global
- update_task, update_task_status
- delete_task
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from ...logging_config import get_logger
from ...schemas.tasks import (
    BatchTaskRequest,
    BatchTaskResponse,
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskStatusUpdate,
    TaskUpdate,
)
from ...storage import log_task_event
from ...storage import task_dependencies as dep_store
from ...storage import tasks as task_store
from ...storage.subtasks import get_subtasks_for_task
from .formatting import get_hints, toon_format_task_list
from .helpers import (
    dispatch_autonomous_task,
    get_step_counts_batch,
    get_step_verification_status,
    get_task_or_404,
    get_worktree_response,
    verify_task_project,
)
from .response import task_to_response

logger = get_logger(__name__)

router = APIRouter()


# Endpoints
@router.get("/projects/{project_id}/tasks", response_model=None)
async def list_tasks(
    project_id: str,
    status: str | None = Query(None, description="Filter by status"),
    task_type: str | None = Query(
        None, alias="type", description="Filter by type (feature, bug, task)"
    ),
    priority: int | None = Query(None, ge=0, le=4, description="Filter by priority (0-4)"),
    labels: str | None = Query(None, description="Filter by labels (comma-separated)"),
    orphans_only: bool = Query(
        False, description="Only return tasks not linked to a feature (issues)"
    ),
    include: str | None = Query(
        None, description="Include related data (e.g., 'feature,blockers')"
    ),
    limit: int = Query(50, ge=1, le=500, description="Results per page"),
    offset: int = Query(0, ge=0, description="Results offset"),
    format: str | None = Query(
        None, description="Output format: 'toon' for compact token-optimized"
    ),
) -> TaskListResponse | PlainTextResponse:
    """List tasks with filtering, pagination, and optional related data."""
    labels_list = labels.split(",") if labels else None
    includes = include.split(",") if include else []
    include_blockers = "blockers" in includes

    tasks = await asyncio.to_thread(
        task_store.list_tasks,
        project_id,
        status_filter=status,
        task_type_filter=task_type,
        priority_filter=priority,
        labels_filter=labels_list,
        orphans_only=orphans_only,
        limit=limit,
        offset=offset,
    )

    # Add blockers info if requested
    if include_blockers:
        for task in tasks:
            blockers = await asyncio.to_thread(dep_store.get_blocking_tasks, task["id"])
            task["blockers"] = blockers

    # Batch fetch criteria counts to avoid N+1 queries
    task_ids = [t["id"] for t in tasks]
    criteria_counts = await asyncio.to_thread(get_step_counts_batch, task_ids)

    task_responses = [task_to_response(t, criteria_counts.get(t["id"], 0)) for t in tasks]

    # Return TOON format if requested
    if format == "toon":
        return PlainTextResponse(
            content=toon_format_task_list(task_responses, endpoint_type="list")
        )

    return TaskListResponse(
        tasks=task_responses,
        total=len(tasks),  # TODO: Add proper total count
        hints=get_hints(task_responses, project_id, endpoint_type="list"),
    )


@router.get("/projects/{project_id}/tasks/ready", response_model=None)
async def list_ready_tasks(
    project_id: str,
    limit: int = Query(50, ge=1, le=500, description="Results per page"),
    format: str | None = Query(
        None, description="Output format: 'toon' for compact token-optimized"
    ),
) -> TaskListResponse | PlainTextResponse:
    """List tasks ready to work on (not blocked by dependencies)."""
    tasks = await asyncio.to_thread(task_store.list_ready_tasks, project_id, limit=limit)

    # Batch fetch criteria counts to avoid N+1 queries
    task_ids = [t["id"] for t in tasks]
    criteria_counts = await asyncio.to_thread(get_step_counts_batch, task_ids)

    task_responses = [task_to_response(t, criteria_counts.get(t["id"], 0)) for t in tasks]

    # Return TOON format if requested
    if format == "toon":
        return PlainTextResponse(
            content=toon_format_task_list(task_responses, endpoint_type="ready")
        )

    return TaskListResponse(
        tasks=task_responses,
        total=len(tasks),
        hints=get_hints(task_responses, project_id, endpoint_type="ready"),
    )


@router.get("/projects/{project_id}/tasks/blocked", response_model=None)
async def list_blocked_tasks(
    project_id: str,
    limit: int = Query(50, ge=1, le=500, description="Results per page"),
    format: str | None = Query(
        None, description="Output format: 'toon' for compact token-optimized"
    ),
) -> TaskListResponse | PlainTextResponse:
    """List tasks blocked by incomplete dependencies."""
    tasks = await asyncio.to_thread(task_store.list_blocked_tasks, project_id, limit=limit)

    # Batch fetch criteria counts to avoid N+1 queries
    task_ids = [t["id"] for t in tasks]
    criteria_counts = await asyncio.to_thread(get_step_counts_batch, task_ids)

    task_responses = [task_to_response(t, criteria_counts.get(t["id"], 0)) for t in tasks]

    # Return TOON format if requested
    if format == "toon":
        return PlainTextResponse(
            content=toon_format_task_list(task_responses, endpoint_type="blocked")
        )

    return TaskListResponse(
        tasks=task_responses,
        total=len(tasks),
        hints=get_hints(task_responses, project_id, endpoint_type="blocked"),
    )


@router.post("/projects/{project_id}/tasks", response_model=TaskResponse)
async def create_task(project_id: str, task: TaskCreate) -> TaskResponse:
    """Create a new task with optional spirit fields."""
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
        autonomous=task.autonomous,
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

    return task_to_response(created)


@router.post("/projects/{project_id}/tasks/batch", response_model=BatchTaskResponse)
async def batch_create_tasks(project_id: str, body: BatchTaskRequest) -> BatchTaskResponse:
    """Create multiple tasks with optional nested subtasks. Handles partial failures."""
    from .crud_handlers import handle_batch_create_tasks

    return await handle_batch_create_tasks(project_id, body)


@router.get("/tasks/{task_id}/completion-readiness")
async def check_completion_readiness(task_id: str) -> dict[str, Any]:
    """Pre-validate completion gates without modifying state."""
    get_task_or_404(task_id)

    subtasks = await asyncio.to_thread(get_subtasks_for_task, task_id)
    incomplete = [s["subtask_id"] for s in subtasks if not s.get("passes")]
    step_status = await asyncio.to_thread(get_step_verification_status, task_id)

    gates: list[dict[str, Any]] = []
    if incomplete:
        gates.append({"gate": "subtasks", "pass": False, "detail": incomplete[:5]})
    if step_status["total"] == 0:
        gates.append({"gate": "zero_steps", "pass": False})
    elif not step_status["all_verified"]:
        gates.append(
            {
                "gate": "steps",
                "pass": False,
                "detail": step_status["unverified"][:5],
            }
        )

    return {"ready": len(gates) == 0, "gates": gates}


@router.get("/tasks/{task_id}", response_model=None)
async def get_task_global(
    task_id: str,
    format: str | None = Query(
        None, description="Output format: 'toon' for compact token-optimized"
    ),
) -> TaskResponse | PlainTextResponse:
    """Get task by ID without project context (for CLI tools)."""
    from .formatting import toon_format_task

    task = await asyncio.to_thread(task_store.get_task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    # Add worktree info if exists
    worktree_response = get_worktree_response(task_id)
    if worktree_response:
        task["worktree"] = worktree_response

    task_response = task_to_response(task)

    # Return TOON format if requested
    if format == "toon":
        return PlainTextResponse(content=toon_format_task(task_response))

    return task_response


@router.get("/projects/{project_id}/tasks/{task_id}", response_model=None)
async def get_task(
    project_id: str,
    task_id: str,
    format: str | None = Query(
        None, description="Output format: 'toon' for compact token-optimized"
    ),
) -> TaskResponse | PlainTextResponse:
    """Get task by ID within project context."""
    from .formatting import toon_format_task

    task = await asyncio.to_thread(verify_task_project, task_id, project_id)

    # Add worktree info if exists
    worktree_response = get_worktree_response(task_id)
    if worktree_response:
        task["worktree"] = worktree_response

    task_response = task_to_response(task)

    # Return TOON format if requested
    if format == "toon":
        return PlainTextResponse(content=toon_format_task(task_response))

    return task_response


@router.patch("/projects/{project_id}/tasks/{task_id}", response_model=TaskResponse)
async def update_task(project_id: str, task_id: str, update: TaskUpdate) -> TaskResponse:
    """Update task fields (splits updates between task and task_spirit tables)."""
    from ...storage.task_spirit import update_task_spirit

    existing = await asyncio.to_thread(verify_task_project, task_id, project_id)

    update_fields = update.model_dump(exclude_unset=True)
    if not update_fields:
        return task_to_response(existing)

    # Split into task fields and spirit fields
    spirit_fields = {"objective", "spirit_anti", "decisions", "constraints", "done_when", "labels"}
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


@router.patch("/projects/{project_id}/tasks/{task_id}/status", response_model=TaskResponse)
async def update_task_status(
    project_id: str, task_id: str, update: TaskStatusUpdate
) -> TaskResponse:
    """Update task status with completion gate validation."""
    await asyncio.to_thread(verify_task_project, task_id, project_id)

    # Gate checks when completing
    # These gates ensure work is actually done before marking complete
    # skip_gates is only for `st close` cleanup path (already merged manually)
    if update.status == "completed" and not update.skip_gates:
        from .crud_handlers import validate_completion_gates

        await validate_completion_gates(task_id)

    try:
        updated = await asyncio.to_thread(
            task_store.update_task_status,
            task_id,
            update.status,
            error_message=update.error_message,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update task status")

    # Log completion reason to events if provided
    if update.reason and update.status in ("completed", "cancelled"):
        await asyncio.to_thread(log_task_event, task_id, f"Closed: {update.reason}")

    # Dispatch autonomous execution tasks on status transitions
    dispatch_autonomous_task(task_id, update.status, project_id)

    # Merge step-level verification into verification_result on completion
    # Preserves existing keys (e.g. execution_clean from autocode pipeline)
    if update.status == "completed" and updated:
        step_status = await asyncio.to_thread(get_step_verification_status, task_id)
        existing = updated.get("verification_result") or {}
        merged = {
            **existing,
            "total": step_status["total"],
            "verified": step_status["verified"],
            "unverified": step_status["unverified"],
            "all_verified": step_status["all_verified"],
        }
        updated = await asyncio.to_thread(
            task_store.update_task, task_id, verification_result=merged
        )

    if updated is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task_to_response(updated)


@router.post("/projects/{project_id}/tasks/{task_id}/execute", response_model=TaskResponse)
async def execute_task(project_id: str, task_id: str) -> TaskResponse:
    """Queue task for autonomous execution via Celery."""
    await asyncio.to_thread(verify_task_project, task_id, project_id)

    try:
        updated = await asyncio.to_thread(task_store.update_task_status, task_id, "queue")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    if not updated:
        raise HTTPException(status_code=500, detail="Failed to start execution")

    # Dispatch autonomous execution
    dispatch_autonomous_task(task_id, "queue", project_id)

    return task_to_response(updated)
