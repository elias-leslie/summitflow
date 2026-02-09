"""Tasks API - List endpoints.

Handles:
- list_tasks: List tasks with filtering, pagination, and optional related data
- list_ready_tasks: List tasks ready to work on (not blocked by dependencies)
- list_blocked_tasks: List tasks blocked by incomplete dependencies
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from ...schemas.tasks import TaskListResponse
from ...storage import task_dependencies as dep_store
from ...storage import tasks as task_store
from .formatting import get_hints, toon_format_task_list
from .helpers import get_step_counts_batch
from .response import task_to_response

router = APIRouter()


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
