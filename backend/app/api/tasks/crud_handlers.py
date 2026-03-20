"""Tasks API - CRUD operation handlers.

Helper functions for complex CRUD operations including:
- Batch task creation
- Task completion gate validation
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException

from ...logging_config import get_logger
from ...schemas.tasks import (
    BatchTaskCreate,
    BatchTaskRequest,
    BatchTaskResponse,
    BatchTaskResult,
    TaskResponse,
)
from ...storage import tasks as task_store
from ...storage.subtasks import get_subtasks_for_task
from .helpers import get_step_verification_status, refresh_task_tracking
from .response import task_to_response

logger = get_logger(__name__)


def _format_batch_error(err_msg: str, item: BatchTaskCreate) -> str:
    """Return a human-friendly error string for a batch create failure."""
    lower = err_msg.lower()
    if "violates foreign key constraint" not in lower:
        return err_msg
    if "capability_id" in lower:
        return f"Capability with id {item.capability_id} not found"
    if "parent_task_id" in lower:
        return f"Parent task {item.parent_task_id} not found"
    return err_msg


async def _save_task_spirit(task_id: str, item: BatchTaskCreate) -> None:
    """Persist spirit fields to the task_spirit table, if any are set."""
    from ...services.task_plan_context import build_task_plan_context
    from ...storage.task_spirit import upsert_task_spirit

    spirit_fields = {"done_when"}
    context = build_task_plan_context(item.model_dump(exclude_none=True))
    has_spirit = (
        any(getattr(item, f, None) for f in spirit_fields)
        or getattr(item, "complexity", None)
        or context
    )
    if not has_spirit:
        return
    try:
        await asyncio.to_thread(
            upsert_task_spirit,
            task_id=task_id,
            done_when=item.done_when,
            context=context or None,
            complexity=item.complexity,
        )
    except Exception as e:
        logger.warning("Failed to create task_spirit for task %s: %s", task_id, e)


async def _create_subtasks_with_deps(task_id: str, item: BatchTaskCreate) -> list[dict[str, Any]] | None:
    """Bulk-create subtasks and their dependencies. Returns created subtask list or None."""
    from ...storage.subtasks import bulk_add_subtask_dependencies, bulk_create_subtasks

    subtasks = getattr(item, "subtasks", None)
    if not subtasks:
        return None

    sub_dicts = [
        {
            "subtask_id": s.subtask_id,
            "phase": s.phase,
            "subtask_type": s.subtask_type,
            "description": s.description,
            "steps": [
                step if isinstance(step, str) else step.model_dump(exclude_none=True)
                for step in s.steps
            ],
            "display_order": s.display_order,
        }
        for s in subtasks
    ]

    try:
        created_subs = await asyncio.to_thread(bulk_create_subtasks, task_id, sub_dicts)
    except Exception as e:
        logger.warning("Failed to create subtasks for task %s: %s", task_id, e)
        return None

    deps = [(s.subtask_id, d) for s in subtasks if s.depends_on for d in s.depends_on]
    if deps:
        try:
            await asyncio.to_thread(bulk_add_subtask_dependencies, task_id, deps)
        except Exception as dep_err:
            logger.warning("Failed dependencies for task %s: %s", task_id, dep_err)

    return created_subs if created_subs else None


async def _create_single_task(project_id: str, item: BatchTaskCreate) -> TaskResponse:
    """Create one task with its spirit fields and subtasks; return its TaskResponse."""
    task = await asyncio.to_thread(
        task_store.create_task,
        project_id=project_id,
        **item.model_dump(
            include={
                "title", "description", "capability_id", "priority",
                "task_type", "parent_task_id", "complexity", "execution_mode", "autonomous",
                "labels",
            }
        ),
    )

    await _save_task_spirit(task["id"], item)

    created_subs = await _create_subtasks_with_deps(task["id"], item)
    if created_subs:
        task["subtasks"] = created_subs
    task = await refresh_task_tracking(task["id"], "batch-create")

    return task_to_response(task)


async def handle_batch_create_tasks(project_id: str, body: BatchTaskRequest) -> BatchTaskResponse:
    """Handle batch task creation with nested subtasks. Handles partial failures."""
    created: list[TaskResponse] = []
    errors: list[BatchTaskResult] = []

    for item in body.items:
        try:
            created.append(await _create_single_task(project_id, item))
        except Exception as e:
            err_msg = _format_batch_error(str(e), item)
            errors.append(BatchTaskResult(title=item.title, success=False, error=err_msg))

    return BatchTaskResponse(created=created, errors=errors)


async def validate_completion_gates(task_id: str) -> None:
    """Validate that a task meets all completion gates: subtasks complete, >0 steps, all verified."""
    subtasks = await asyncio.to_thread(get_subtasks_for_task, task_id)
    if incomplete := [s["subtask_id"] for s in subtasks if not s.get("passes")]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Cannot complete task with incomplete subtasks",
                "incomplete_subtasks": incomplete,
                "what_to_do": [f"Complete subtask {s} using: st subtask pass {task_id} {s}" for s in incomplete[:5]],
                "remaining": len(incomplete),
            },
        )

    step_status = await asyncio.to_thread(get_step_verification_status, task_id)
    # Steps are optional progress trackers — zero steps is valid for bare/intent-only tasks
    if step_status["total"] > 0 and not step_status["all_verified"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Cannot complete task with incomplete steps",
                "unverified_steps": step_status["unverified"][:10],
                "remaining": len(step_status["unverified"]),
                "what_to_do": [
                    "Complete all steps before closing the task",
                    f"Run: st context {task_id} to see remaining steps",
                ],
            },
        )
