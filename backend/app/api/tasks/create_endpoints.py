"""Tasks API - Create endpoints.

Handles:
- create_task: Create a new task with optional spirit fields
- batch_create_tasks: Create multiple tasks with optional nested subtasks
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from ...schemas.tasks import BatchTaskRequest, BatchTaskResponse, TaskCreate, TaskResponse
from ...storage import tasks as task_store
from .response import task_to_response

router = APIRouter()


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
