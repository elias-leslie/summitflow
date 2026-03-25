"""Tasks API - Get endpoints.

Handles:
- get_task_global: Get task by ID without project context (for CLI tools)
- get_task: Get task by ID within project context
- check_completion_readiness: Pre-validate completion gates without modifying state
- review_task: Run AI reviewer on task diff
"""

from __future__ import annotations

import asyncio
from typing import Any

from agent_hub.models import MessageInput, ToolResultMessage
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from ...schemas.tasks import TaskResponse
from ...storage import tasks as task_store
from ...storage.subtasks import get_subtasks_for_task
from ...tasks.autonomous._project_resolution import resolve_task_project_id
from .formatting import toon_format_task
from .helpers import (
    get_task_or_404,
    get_worktree_response,
    verify_task_project,
)
from .response import task_to_response

router = APIRouter()


@router.get("/tasks/{task_id}/completion-readiness")
async def check_completion_readiness(task_id: str) -> dict[str, Any]:
    """Pre-validate completion gates without modifying state."""
    task = get_task_or_404(task_id)
    canonical_task_id = str(task["id"])

    subtasks = await asyncio.to_thread(get_subtasks_for_task, canonical_task_id)
    incomplete = [s["subtask_id"] for s in subtasks if not s.get("passes")]

    gates: list[dict[str, Any]] = []
    if incomplete:
        gates.append({"gate": "subtasks", "pass": False, "detail": incomplete[:5]})

    return {"ready": not gates, "gates": gates}


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
    canonical_task_id = str(task["id"])

    # Add worktree info if exists
    worktree_response = get_worktree_response(canonical_task_id)
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
    canonical_task_id = str(task["id"])

    # Add worktree info if exists
    worktree_response = get_worktree_response(canonical_task_id)
    if worktree_response:
        task["worktree"] = worktree_response

    task_response = task_to_response(task)

    # Return TOON format if requested
    if format == "toon":
        return PlainTextResponse(content=toon_format_task(task_response))

    return task_response


@router.post("/tasks/{task_id}/review")
async def review_task(task_id: str) -> dict[str, Any]:
    """Run AI reviewer on task diff. Returns verdict without side effects."""
    from ...services.agent_hub_client import get_sync_client
    from ...tasks.autonomous.review import _build_prompt
    from ...tasks.autonomous.review_modules.diff import get_git_diff
    from ...tasks.autonomous.review_modules.parsing import parse_review_response

    task = get_task_or_404(task_id)
    project_id = resolve_task_project_id(task)

    git_diff = await asyncio.to_thread(get_git_diff, task_id, project_id)
    if not git_diff or git_diff.strip() in ("(no changes)", ""):
        return {"verdict": "REJECTED", "concerns": [], "summary": "No code changes detected"}
    prompt = await asyncio.to_thread(
        _build_prompt,
        task,
        str(task.get("complexity") or "STANDARD"),
        git_diff,
        task_id,
    )

    client = await asyncio.to_thread(get_sync_client)
    messages: list[dict[str, str] | MessageInput | ToolResultMessage] = [
        MessageInput(role="user", content=prompt)
    ]
    response = await asyncio.to_thread(
        client.complete,
        agent_slug="reviewer",
        messages=messages,
        project_id=project_id,
        execute_tools=False,
    )
    result = parse_review_response(response.content)
    return {
        "verdict": result.get("verdict", "UNKNOWN"),
        "concerns": result.get("concerns", []),
        "summary": result.get("summary", ""),
    }
