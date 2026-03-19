"""Tasks API - Workflow endpoints.

Handles plan approval, context retrieval, export, and logs:
- POST /approve: Approve a task's plan
- GET /context: Full task context (TOON default)
- GET /export: Complete task JSON for plan.json round-trip
- GET /logs: Task progress log entries (TOON default)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from ...services.task_execution_readiness import assess_task_execution_readiness
from ...services.task_lane_preflight import check_task_lane_conflicts
from ...storage import task_dependencies as dep_store
from ...storage.events import get_events_by_trace
from ...storage.subtasks import get_subtasks_for_task
from ...storage.task_spirit import get_task_spirit
from .helpers import verify_task_project
from .workflow_approval import approve_task_plan_impl
from .workflow_export import build_export_data
from .workflow_formatters import build_context_json, format_logs_toon, format_toon_context
from .workflow_models import PlanApproveRequest, PlanApproveResponse

router = APIRouter()


# Endpoints
@router.post("/projects/{project_id}/tasks/{task_id}/approve", response_model=PlanApproveResponse)
async def approve_task_plan(
    project_id: str,
    task_id: str,
    body: PlanApproveRequest | None = None,
) -> PlanApproveResponse:
    """Approve a task's plan, allowing execution to start.

    Args:
        project_id: Project ID
        task_id: Task ID
        body: Optional approval details (approved_by, notes)

    Returns:
        PlanApproveResponse with updated plan status
    """
    verify_task_project(task_id, project_id)

    approved_by = body.approved_by if body else "user"
    notes = body.notes if body else None

    try:
        result = approve_task_plan_impl(task_id, approved_by, notes)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return PlanApproveResponse(
        task_id=task_id,
        plan_status=result["plan_status"],
        plan_approved_at=result["plan_approved_at"],
        plan_approved_by=result["plan_approved_by"],
        message=f"Plan approved for task {task_id}",
    )


@router.get("/projects/{project_id}/tasks/{task_id}/context", response_model=None)
async def get_task_context(
    project_id: str,
    task_id: str,
    format: str | None = Query(
        None, description="Output format: 'json' for JSON (default is TOON)"
    ),
) -> PlainTextResponse | dict[str, Any]:
    """Get full task context including spirit, subtasks, steps, and blockers.

    Returns TOON format by default (matches st context output).
    Use ?format=json for JSON response.

    Args:
        project_id: Project ID
        task_id: Task ID
        format: Output format ('json' for JSON, default is TOON)
    """
    task = verify_task_project(task_id, project_id)

    # Get spirit data
    spirit = get_task_spirit(task_id)

    # Get subtasks with steps
    subtasks = get_subtasks_for_task(task_id, include_steps=False)

    # Get blockers
    blockers = dep_store.get_blocking_tasks(task_id)

    lane_check = check_task_lane_conflicts(task_id, project_id)

    if format == "json":
        return build_context_json(task, spirit, subtasks, blockers, lane_check)

    # Default: TOON format
    readiness = assess_task_execution_readiness(task, spirit, get_subtasks_for_task(task_id, include_steps=True))
    return PlainTextResponse(content=format_toon_context(task, spirit, subtasks, blockers, readiness, lane_check))


@router.get("/projects/{project_id}/tasks/{task_id}/export")
async def export_task(
    project_id: str,
    task_id: str,
) -> dict[str, Any]:
    """Export complete task data for plan.json round-trip.

    Returns all nested data including:
    - Task basic info
    - Spirit (objective, done_when, context, etc.)
    - Acceptance criteria
    - Subtasks with steps
    - Dependencies
    - Progress log

    Args:
        project_id: Project ID
        task_id: Task ID
    """
    task = verify_task_project(task_id, project_id)

    # Get spirit data
    spirit = get_task_spirit(task_id)

    # Get subtasks
    subtasks = get_subtasks_for_task(task_id, include_steps=False)

    return build_export_data(task, spirit, subtasks)


@router.get("/projects/{project_id}/tasks/{task_id}/logs", response_model=None)
async def get_task_logs(
    project_id: str,
    task_id: str,
    format: str | None = Query(
        None, description="Output format: 'json' for JSON (default is TOON)"
    ),
) -> PlainTextResponse | dict[str, Any]:
    """Get task progress log entries.

    Returns TOON format by default:
    ```
    LOGS[3]:task-abc123
    [2026-01-23 10:00] Plan defect in subtask 1.2...
    [2026-01-23 11:00] Gap analysis completed...
    [2026-01-23 12:00] Session paused at subtask 2.1
    ```

    Use ?format=json for JSON response.

    Args:
        project_id: Project ID
        task_id: Task ID
        format: Output format ('json' for JSON, default is TOON)
    """
    verify_task_project(task_id, project_id)

    # Get progress log from events table
    events = get_events_by_trace(task_id, visibility="user", limit=500)
    progress_log = [
        f"[{e['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}] {e['message']}"
        for e in events
        if e.get("message")
    ]

    if format == "json":
        return {"task_id": task_id, "entries": progress_log, "count": len(progress_log)}

    # Default: TOON format
    return PlainTextResponse(content=format_logs_toon(task_id, progress_log))
