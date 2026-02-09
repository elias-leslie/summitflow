"""Tasks API - Get endpoints.

Handles:
- get_task_global: Get task by ID without project context (for CLI tools)
- get_task: Get task by ID within project context
- check_completion_readiness: Pre-validate completion gates without modifying state
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from ...schemas.tasks import TaskResponse
from ...storage import tasks as task_store
from ...storage.subtasks import get_subtasks_for_task
from .formatting import toon_format_task
from .helpers import (
    get_step_verification_status,
    get_task_or_404,
    get_worktree_response,
    verify_task_project,
)
from .response import task_to_response

router = APIRouter()


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
