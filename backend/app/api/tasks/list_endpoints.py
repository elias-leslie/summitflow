"""Tasks API - List endpoints.

Handles:
- list_tasks: List tasks with filtering, pagination, and optional related data
- list_ready_tasks: List tasks ready to work on (not blocked by dependencies)
- list_blocked_tasks: List tasks blocked by incomplete dependencies
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from ...schemas.tasks import TaskListResponse
from ...storage import task_dependencies as dep_store
from ...storage import tasks as task_store
from .formatting import get_hints, toon_format_task_list
from .helpers import get_step_counts_batch
from .response import task_to_response

router = APIRouter()


def _build_filter_kwargs(
    status: str | None,
    task_type: str | None,
    priority: int | None,
    labels_list: list[str] | None,
    orphans_only: bool,
) -> dict[str, Any]:
    """Build filter kwargs dict for task store queries."""
    return dict(
        status_filter=status,
        task_type_filter=task_type,
        priority_filter=priority,
        labels_filter=labels_list,
        orphans_only=orphans_only,
    )


async def _enrich_tasks_with_blockers(
    tasks: list[dict[str, Any]], task_ids: list[str]
) -> None:
    """Add blockers info to each task dict (mutates tasks in-place)."""
    blockers_map = await asyncio.to_thread(dep_store.get_blocking_tasks_batch, task_ids)
    for task in tasks:
        task["blockers"] = blockers_map.get(task["id"], [])


async def _fetch_filtered_tasks(
    project_id: str,
    filter_kwargs: dict[str, Any],
    limit: int,
    offset: int,
    include_blockers: bool,
) -> tuple[list[dict[str, Any]], int]:
    """Fetch tasks and total count, optionally enriching with blockers."""
    tasks, total = await asyncio.gather(
        asyncio.to_thread(
            task_store.list_tasks, project_id, **filter_kwargs, limit=limit, offset=offset,
        ),
        asyncio.to_thread(task_store.count_tasks, project_id, **filter_kwargs),
    )
    if include_blockers:
        task_ids = [t["id"] for t in tasks]
        await _enrich_tasks_with_blockers(tasks, task_ids)
    return tasks, total


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
    include_blockers = "blockers" in (include.split(",") if include else [])
    filter_kwargs = _build_filter_kwargs(status, task_type, priority, labels_list, orphans_only)

    tasks, total = await _fetch_filtered_tasks(
        project_id, filter_kwargs, limit, offset, include_blockers
    )

    task_ids = [t["id"] for t in tasks]
    criteria_counts = await asyncio.to_thread(get_step_counts_batch, task_ids)
    task_responses = [task_to_response(t, criteria_counts.get(t["id"], 0)) for t in tasks]

    if format == "toon":
        return PlainTextResponse(
            content=toon_format_task_list(task_responses, endpoint_type="list")
        )

    return TaskListResponse(
        tasks=task_responses,
        total=total,
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
    from ...services.task_execution_readiness import sync_task_execution_readiness

    candidate_limit = min(limit * 5, 500)
    tasks = await asyncio.to_thread(task_store.list_ready_tasks, project_id, limit=candidate_limit)
    ready_tasks: list[dict[str, object]] = []
    for task in tasks:
        readiness = await asyncio.to_thread(sync_task_execution_readiness, task["id"])
        if readiness.ready:
            ready_tasks.append(task)
        if len(ready_tasks) >= limit:
            break

    # Batch fetch criteria counts to avoid N+1 queries
    task_ids = [t["id"] for t in ready_tasks]
    criteria_counts = await asyncio.to_thread(get_step_counts_batch, task_ids)

    task_responses = [task_to_response(t, criteria_counts.get(t["id"], 0)) for t in ready_tasks]

    # Return TOON format if requested
    if format == "toon":
        return PlainTextResponse(
            content=toon_format_task_list(task_responses, endpoint_type="ready")
        )

    return TaskListResponse(
        tasks=task_responses,
        total=len(ready_tasks),
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
