"""Tasks API - Create endpoints.

Handles create_task, batch_create_tasks, and create_task_from_ideation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

from fastapi import APIRouter, HTTPException, Request

from ...access_control import require_owner
from ...logging_config import get_logger
from ...schemas.tasks import (
    BatchTaskRequest,
    BatchTaskResponse,
    IdeationTaskCreate,
    IdeationTaskResponse,
    TaskCreate,
    TaskResponse,
)
from ...services.task_plan_context import build_task_plan_context
from ...storage import tasks as task_store
from ...storage.tasks.core import ExternalTaskConflict, ExternalTaskUnavailable
from ...storage.tasks.execution_mode import normalize_execution_fields
from .helpers import refresh_task_tracking
from .response import task_to_response

router = APIRouter()
logger = get_logger(__name__)


async def _save_spirit_fields(task_id: str, task: TaskCreate) -> None:
    """Persist spirit fields to task_spirit table if any are provided."""
    from ...services.task_plan_context import build_task_plan_context
    from ...storage.task_spirit import upsert_task_spirit

    context = build_task_plan_context(
        {
            "objective": task.objective,
            "spirit_anti": task.spirit_anti,
            "decisions": task.decisions,
            "constraints": task.constraints,
        }
    )
    if not any([task.done_when, task.complexity, context]):
        return

    await asyncio.to_thread(
        upsert_task_spirit,
        task_id=task_id,
        done_when=task.done_when,
        context=context or None,
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
        if spirit and spirit.get("done_when"):
            task_store.update_task(task_id, complexity="STANDARD")


@router.post("/projects/{project_id}/tasks", response_model=TaskResponse)
async def create_task(project_id: str, task: TaskCreate, request: Request) -> TaskResponse:
    """Create a new pending task."""
    execution_fields = normalize_execution_fields(
        task_type=task.task_type,
        execution_mode=task.execution_mode,
        autonomous=task.autonomous,
    )
    extra = {}
    if task.external_origin is not None:
        principal = require_owner(request)
        payload = task.model_dump(mode="json", exclude={"external_origin", "external_request_key", "autonomous"})
        payload["execution_mode"] = execution_fields["execution_mode"]
        payload["project_id"] = project_id
        extra["external_identity"] = {
            "principal_scope": hashlib.sha256(principal.email.encode()).hexdigest(),
            "external_origin": task.external_origin,
            "external_request_key": task.external_request_key,
            "external_payload_digest": hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            ).hexdigest(),
        }
        extra["initial_spirit"] = {
            "done_when": task.done_when,
            "context": build_task_plan_context(task.model_dump()),
            "complexity": task.complexity,
        }
    try:
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
            labels=task.labels,
            ai_review=task.ai_review,
            **extra,
        )
    except ExternalTaskConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ExternalTaskUnavailable as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc

    if created.pop("_external_reused", False):
        return task_to_response(created)
    if not extra:
        await _save_spirit_fields(created["id"], task)
    _auto_classify_complexity(created)
    created = await refresh_task_tracking(created["id"], "task-create")
    return task_to_response(created)


@router.post("/projects/{project_id}/tasks/from-ideation", response_model=IdeationTaskResponse)
async def create_task_from_ideation(
    project_id: str, body: IdeationTaskCreate
) -> IdeationTaskResponse:
    """Create a pending task from ideation chat output. Normalizes complexity to DB enum."""
    created = await asyncio.to_thread(
        task_store.create_task,
        project_id=project_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        task_type=body.task_type,
        complexity=body.to_db_complexity(),
        labels=body.labels,
    )

    task_id = created["id"]
    await refresh_task_tracking(task_id, "ideation-create")
    return IdeationTaskResponse(task_id=task_id, project_id=project_id, status="pending")


@router.post("/projects/{project_id}/tasks/batch", response_model=BatchTaskResponse)
async def batch_create_tasks(project_id: str, body: BatchTaskRequest) -> BatchTaskResponse:
    """Create multiple tasks with optional nested subtasks. Handles partial failures."""
    from .crud_handlers import handle_batch_create_tasks

    return await handle_batch_create_tasks(project_id, body)
