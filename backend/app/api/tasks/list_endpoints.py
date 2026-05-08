"""Tasks API - List endpoints.

Handles:
- list_tasks: List tasks with filtering, pagination, and optional related data
- list_ready_tasks: List tasks ready to work on (not blocked by dependencies)
- list_blocked_tasks: List tasks blocked by incomplete dependencies
- ready_all_overview: Cross-project ready/blocked/active/stale overview for agentic consumers
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from cli.commands.tasks_ready_all import lane_task_id, render_ready_all_compact, task_sort_key

from ...logging_config import get_logger
from ...schemas.tasks import TaskListResponse
from ...services._lane_inventory import fetch_live_project_inventory
from ...services.ready_task_ranking import sort_ready_tasks
from ...storage import projects as project_store
from ...storage import task_dependencies as dep_store
from ...storage import tasks as task_store
from .formatting import get_hints, toon_format_task_list
from .helpers import has_active_checkpoint
from .response import task_to_response

router = APIRouter()
logger = get_logger(__name__)


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


async def _collect_execution_ready_tasks(
    project_id: str,
    limit: int,
    exclude_task_ids: set[str] | None = None,
) -> tuple[list[dict[str, object]], int]:
    """Collect execution-ready tasks using the same readiness scan as /tasks/ready."""
    from ...services.task_execution_readiness import sync_task_execution_readiness

    scan_batch_size = min(max(limit * 10, 25), 100)
    scan_offset = 0
    ready_tasks: list[dict[str, object]] = []
    total_ready = 0
    excluded = exclude_task_ids or set()

    while scan_offset < 500:
        tasks = await asyncio.to_thread(
            task_store.list_ready_tasks,
            project_id,
            limit=scan_batch_size,
            offset=scan_offset,
        )
        if not tasks:
            break

        # Run readiness checks concurrently instead of sequentially (N+1 fix)
        readiness_results = await asyncio.gather(
            *(asyncio.to_thread(sync_task_execution_readiness, task["id"]) for task in tasks)
        )
        for task, readiness in zip(tasks, readiness_results, strict=True):
            if not readiness.ready:
                continue
            task_id = str(task.get("id") or "")
            if task_id in excluded:
                continue
            if has_active_checkpoint(task_id, project_id):
                continue
            total_ready += 1
            ready_tasks.append(task)

        if len(tasks) < scan_batch_size:
            break
        scan_offset += scan_batch_size

    ranked_tasks = sort_ready_tasks([dict(task) for task in ready_tasks])
    return ranked_tasks[:limit], total_ready


async def _fetch_live_lane_task_ids(project_id: str) -> set[str]:
    """Return live task ids with active owner/specialist evidence from Agent Hub."""
    try:
        owner_sessions, specialist_rows = await asyncio.to_thread(fetch_live_project_inventory, project_id)
    except Exception as exc:
        logger.warning(
            "ready_tasks_live_inventory_unavailable",
            project_id=project_id,
            error=str(exc),
        )
        return set()
    live_task_ids = {
        task_id
        for session in owner_sessions
        if (task_id := lane_task_id(session))
    }
    live_task_ids.update(
        str(row.get("task_id"))
        for row in specialist_rows
        if isinstance(row.get("task_id"), str) and row.get("task_id")
    )
    return live_task_ids


async def _collect_ready_all_project_data(
    project_id: str,
    project_name: str,
    limit_per_project: int,
) -> dict[str, Any]:
    """Collect the canonical ready-all data for one project without self-HTTP."""
    live_lane_task_ids = await _fetch_live_lane_task_ids(project_id)
    ready_tasks, ready_count = await _collect_execution_ready_tasks(
        project_id,
        limit_per_project,
        exclude_task_ids=live_lane_task_ids,
    )
    blocked_tasks = await asyncio.to_thread(task_store.list_blocked_tasks, project_id, limit=limit_per_project)
    pending_tasks, running_tasks = await asyncio.gather(
        asyncio.to_thread(task_store.list_tasks, project_id, status_filter="pending", limit=100, offset=0),
        asyncio.to_thread(task_store.list_tasks, project_id, status_filter="running", limit=100, offset=0),
    )

    active_tasks: list[dict[str, object]] = [
        task
        for task in pending_tasks
        if str(task.get("id") or "") in live_lane_task_ids
        or has_active_checkpoint(str(task.get("id") or ""), project_id)
    ]
    stale_tasks: list[dict[str, object]] = []
    for task in running_tasks:
        task_id = str(task.get("id") or "")
        if task_id in live_lane_task_ids or has_active_checkpoint(task_id, project_id):
            active_tasks.append(task)
        else:
            stale_tasks.append(task)

    return {
        "project_id": project_id,
        "project_name": project_name,
        "ready_tasks": sorted(ready_tasks, key=task_sort_key),
        "ready_count": ready_count,
        "blocked_tasks": sorted(blocked_tasks, key=task_sort_key),
        "blocked_count": len(blocked_tasks),
        "active_tasks": active_tasks,
        "active_count": len(active_tasks),
        "stale_tasks": stale_tasks,
        "stale_count": len(stale_tasks),
    }


def _empty_ready_all_response() -> dict[str, object]:
    """Return a ready-all response with zero counts and no projects."""
    return {
        "payload": {
            "summary": {"ready": 0, "blocked": 0, "active": 0, "stale": 0, "projects": 0},
            "projects": [],
        },
        "raw": "",
    }


def _assemble_ready_all_response(
    ordered_results: list[dict[str, Any]], limit_per_project: int
) -> dict[str, object]:
    """Build the final ready-all response from sorted project results."""
    return {
        "payload": {
            "summary": {
                "ready": sum(int(item["ready_count"]) for item in ordered_results),
                "blocked": sum(int(item["blocked_count"]) for item in ordered_results),
                "active": sum(int(item["active_count"]) for item in ordered_results),
                "stale": sum(int(item["stale_count"]) for item in ordered_results),
                "projects": len(ordered_results),
            },
            "projects": ordered_results,
        },
        "raw": render_ready_all_compact(ordered_results, limit_per_project),
    }


async def _build_ready_all_overview_response(
    *,
    limit_per_project: int,
    project_id: str | None = None,
) -> dict[str, object]:
    """Build the canonical ready-all API response with payload plus rendered text."""
    projects = await asyncio.to_thread(project_store.list_projects)
    if project_id is not None:
        projects = [p for p in projects if p.get("id") == project_id]

    if not projects:
        return _empty_ready_all_response()

    results = await asyncio.gather(
        *[
            _collect_ready_all_project_data(
                str(project.get("id") or ""),
                str(project.get("name") or project.get("id") or ""),
                limit_per_project,
            )
            for project in projects
            if project.get("id")
        ]
    )
    ordered_results = sorted(
        results,
        key=lambda item: (
            -int(item["blocked_count"]),
            -int(item["stale_count"]),
            -int(item["active_count"]),
            -int(item["ready_count"]),
        ),
    )
    return _assemble_ready_all_response(ordered_results, limit_per_project)


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

    task_responses = [task_to_response(t) for t in tasks]

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
    live_lane_task_ids = await _fetch_live_lane_task_ids(project_id)
    ready_tasks, total_ready = await _collect_execution_ready_tasks(
        project_id,
        limit,
        exclude_task_ids=live_lane_task_ids,
    )

    task_responses = [task_to_response(t) for t in ready_tasks]

    # Return TOON format if requested
    if format == "toon":
        return PlainTextResponse(
            content=toon_format_task_list(task_responses, endpoint_type="ready")
        )

    return TaskListResponse(
        tasks=task_responses,
        total=total_ready,
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

    task_responses = [task_to_response(t) for t in tasks]

    # Return TOON format if requested
    if format == "toon":
        return PlainTextResponse(
            content=toon_format_task_list(task_responses, endpoint_type="failed")
        )

    return TaskListResponse(
        tasks=task_responses,
        total=len(tasks),
        hints=get_hints(task_responses, project_id, endpoint_type="failed"),
    )


@router.get("/tasks/ready-all", response_model=None)
async def ready_all_overview(
    limit: int = Query(3, ge=1, le=20, description="Top tasks shown per project"),
) -> dict[str, object]:
    """Return the canonical cross-project ready-all overview with rendered text."""
    return await _build_ready_all_overview_response(limit_per_project=limit)


@router.get("/projects/{project_id}/tasks/ready-all", response_model=None)
async def project_ready_all_overview(
    project_id: str,
    limit: int = Query(3, ge=1, le=20, description="Top tasks shown for the project"),
) -> dict[str, object]:
    """Return the canonical ready-all overview for a single project."""
    return await _build_ready_all_overview_response(limit_per_project=limit, project_id=project_id)
