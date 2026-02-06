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
from ...schemas.tasks import BatchTaskRequest, BatchTaskResponse, BatchTaskResult, TaskResponse
from ...storage import tasks as task_store
from ...storage.subtasks import get_subtasks_for_task
from .helpers import get_step_verification_status
from .response import task_to_response

logger = get_logger(__name__)


async def handle_batch_create_tasks(
    project_id: str, body: BatchTaskRequest
) -> BatchTaskResponse:
    """Handle batch task creation with nested subtasks.

    Handles partial failures: returns both created tasks and errors.
    Each task is created independently, so failures don't rollback successes.

    Supports nested subtasks: if item.subtasks is provided, bulk_create_subtasks
    is called automatically. Subtask steps are created in the normalized table.

    Args:
        project_id: Project ID
        body: List of tasks to create (with optional capability_id linkages)

    Returns:
        BatchTaskResponse with created tasks and any errors.
    """
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
                title=item.title,
                description=item.description,
                capability_id=item.capability_id,
                priority=item.priority,
                task_type=item.task_type,
                parent_task_id=item.parent_task_id,
                complexity=item.complexity,
                autonomous=item.autonomous,
            )

            # Save spirit fields to task_spirit table
            if (
                item.objective
                or item.spirit_anti
                or item.decisions
                or item.constraints
                or item.done_when
            ):
                try:
                    await asyncio.to_thread(
                        upsert_task_spirit,
                        task_id=task["id"],
                        objective=item.objective or "",
                        spirit_anti=item.spirit_anti,
                        decisions=item.decisions,
                        constraints=item.constraints,
                        done_when=item.done_when,
                        complexity=item.complexity,
                    )
                except Exception as spirit_err:
                    logger.warning(
                        f"Failed to create task_spirit for task {task['id']}: {spirit_err}"
                    )

            # Create nested subtasks if provided
            created_subtasks = None
            if item.subtasks:
                try:
                    subtask_dicts = []
                    for s in item.subtasks:
                        # Convert StepInput models to dicts for storage layer
                        steps_as_dicts: list[str | dict[str, Any]] = []
                        for step in s.steps:
                            if isinstance(step, str):
                                steps_as_dicts.append(step)
                            else:
                                step_dict: dict[str, Any] = {"description": step.description}
                                if step.spec:
                                    step_dict["spec"] = step.spec
                                if step.verify_command:
                                    step_dict["verify_command"] = step.verify_command
                                if step.expected_output:
                                    step_dict["expected_output"] = step.expected_output
                                steps_as_dicts.append(step_dict)
                        subtask_dicts.append(
                            {
                                "subtask_id": s.subtask_id,
                                "phase": s.phase,
                                "description": s.description,
                                "steps": steps_as_dicts,
                                "display_order": s.display_order,
                            }
                        )
                    created_subtasks = await asyncio.to_thread(
                        bulk_create_subtasks, task["id"], subtask_dicts
                    )

                    # Handle subtask dependencies
                    dependencies: list[tuple[str, str]] = []
                    for s in item.subtasks:
                        if s.depends_on:
                            for dep in s.depends_on:
                                dependencies.append((s.subtask_id, dep))
                    if dependencies:
                        try:
                            await asyncio.to_thread(
                                bulk_add_subtask_dependencies, task["id"], dependencies
                            )
                        except Exception as dep_err:
                            logger.warning(  # type: ignore[call-arg]
                                "Failed to create dependencies for task %s: %s",
                                task["id"],
                                dep_err,
                            )
                except Exception as e:
                    logger.warning(  # type: ignore[call-arg]
                        "Failed to create subtasks for task %s: %s", task["id"], e
                    )
                    # Continue - task succeeded, subtasks failed (partial success)

            # Include subtasks in response if created
            if created_subtasks:
                task["subtasks"] = created_subtasks

            created.append(task_to_response(task))
        except Exception as e:
            error_msg = str(e)
            if "violates foreign key constraint" in error_msg.lower():
                if "capability_id" in error_msg.lower():
                    error_msg = f"Capability with id {item.capability_id} not found"
                elif "parent_task_id" in error_msg.lower():
                    error_msg = f"Parent task {item.parent_task_id} not found"
            errors.append(
                BatchTaskResult(
                    title=item.title,
                    success=False,
                    error=error_msg,
                )
            )

    return BatchTaskResponse(created=created, errors=errors)


async def validate_completion_gates(task_id: str) -> None:
    """Validate that a task meets all completion gates.

    Gates:
    1. All subtasks must be complete
    2. Task must have at least one step
    3. All steps must be verified

    Raises:
        HTTPException(422): If any gate fails
    """
    # Gate 1: All subtasks must be complete
    subtasks = await asyncio.to_thread(get_subtasks_for_task, task_id)
    incomplete_subtasks = [s["subtask_id"] for s in subtasks if not s.get("passes")]
    if incomplete_subtasks:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Cannot complete task with incomplete subtasks",
                "incomplete_subtasks": incomplete_subtasks,
                "what_to_do": [
                    f"Complete subtask {s} using: st subtask pass {task_id} {s}"
                    for s in incomplete_subtasks[:5]  # Show first 5
                ],
                "remaining": len(incomplete_subtasks),
            },
        )

    # Gate 2: Task must have at least one verified step
    # Note: Step verify_commands are run when marking steps as passed, not here
    step_status = await asyncio.to_thread(get_step_verification_status, task_id)

    # Gate 2a: Cannot complete task with zero steps (verification is mandatory)
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

    # Gate 2b: All steps must be verified
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
