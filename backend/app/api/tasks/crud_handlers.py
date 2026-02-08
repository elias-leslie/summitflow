"""Tasks API - CRUD operation handlers.

Helper functions for complex CRUD operations including:
- Batch task creation
- Task completion gate validation
"""

from __future__ import annotations

import asyncio

from fastapi import HTTPException

from ...logging_config import get_logger
from ...schemas.tasks import BatchTaskRequest, BatchTaskResponse, BatchTaskResult, TaskResponse
from ...storage import tasks as task_store
from ...storage.subtasks import get_subtasks_for_task
from .helpers import get_step_verification_status
from .response import task_to_response

logger = get_logger(__name__)


async def handle_batch_create_tasks(project_id: str, body: BatchTaskRequest) -> BatchTaskResponse:
    """Handle batch task creation with nested subtasks. Handles partial failures."""
    from ...storage.subtasks import bulk_add_subtask_dependencies, bulk_create_subtasks
    from ...storage.task_spirit import upsert_task_spirit

    created: list[TaskResponse] = []
    errors: list[BatchTaskResult] = []

    for item in body.items:
        try:
            # Create task (basic fields only)
            task = await asyncio.to_thread(
                task_store.create_task,
                project_id=project_id,
                **item.model_dump(
                    include={
                        "title", "description", "capability_id", "priority",
                        "task_type", "parent_task_id", "complexity", "autonomous"
                    }
                ),
            )

            # Save spirit fields to task_spirit table
            spirit_fields = {"objective", "spirit_anti", "decisions", "constraints", "done_when"}
            if any(getattr(item, f) for f in spirit_fields) or item.complexity:
                try:
                    await asyncio.to_thread(
                        upsert_task_spirit,
                        task_id=task["id"],
                        objective=item.objective or "",
                        **item.model_dump(include={"spirit_anti", "decisions", "constraints", "done_when", "complexity"}),
                    )
                except Exception as e:
                    logger.warning(f"Failed to create task_spirit for task {task['id']}: {e}")

            # Create nested subtasks if provided
            if item.subtasks:
                try:
                    sub_dicts = [
                        {
                            "subtask_id": s.subtask_id,
                            "phase": s.phase,
                            "description": s.description,
                            "steps": [
                                step if isinstance(step, str) else step.model_dump(exclude_none=True)
                                for step in s.steps
                            ],
                            "display_order": s.display_order,
                        }
                        for s in item.subtasks
                    ]
                    created_subs = await asyncio.to_thread(bulk_create_subtasks, task["id"], sub_dicts)
                    
                    # Handle subtask dependencies
                    deps = [(s.subtask_id, d) for s in item.subtasks if s.depends_on for d in s.depends_on]
                    if deps:
                        try:
                            await asyncio.to_thread(bulk_add_subtask_dependencies, task["id"], deps)
                        except Exception as dep_err:
                            logger.warning(f"Failed dependencies for task {task['id']}: {dep_err}")
                    
                    if created_subs:
                        task["subtasks"] = created_subs
                except Exception as e:
                    logger.warning(f"Failed to create subtasks for task {task['id']}: {e}")

            created.append(task_to_response(task))
        except Exception as e:
            err_msg = str(e)
            if "violates foreign key constraint" in err_msg.lower():
                if "capability_id" in err_msg.lower():
                    err_msg = f"Capability with id {item.capability_id} not found"
                elif "parent_task_id" in err_msg.lower():
                    err_msg = f"Parent task {item.parent_task_id} not found"
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
    if step_status["total"] == 0:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Cannot complete task with zero steps",
                "total_steps": 0,
                "what_to_do": [
                    "Every task must have at least one step with verify_command",
                    "Create subtasks with steps, or import a proper plan.json",
                ],
            },
        )

    if not step_status["all_verified"]:
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
