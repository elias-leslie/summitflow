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
from pydantic import BaseModel

from ...logging_config import get_logger
from ...services.task_continuity import build_continuity
from ...services.task_execution_readiness import (
    assess_task_execution_readiness,
    is_final_task_status,
)
from ...services.task_lane_preflight import check_task_lane_conflicts
from ...storage import task_dependencies as dep_store
from ...storage import tasks as task_store
from ...storage.events import get_events_by_trace
from ...storage.subtasks import get_subtask_summary, get_subtasks_for_task
from ...storage.task_spirit import approve_plan, create_task_spirit, get_task_spirit
from .helpers import get_task_or_404, verify_task_project
from .workflow_export import build_export_data
from .workflow_formatters import build_context_json, format_logs_toon, format_toon_context

logger = get_logger(__name__)
router = APIRouter()


# --- Models ---


class PlanApproveRequest(BaseModel):
    """Request body for plan approval."""

    approved_by: str = "user"
    notes: str | None = None


class PlanApproveResponse(BaseModel):
    """Response for plan approval."""

    task_id: str
    plan_status: str
    plan_approved_at: str | None
    plan_approved_by: str | None
    message: str


# --- Approval impl ---


def approve_task_plan_impl(task_id: str, approved_by: str, notes: str | None) -> dict[str, Any]:
    """Approve task plan, creating task_spirit if needed.

    Args:
        task_id: Task ID
        approved_by: User who approved the plan
        notes: Optional approval notes

    Returns:
        Approval result with plan_status, plan_approved_at, plan_approved_by

    Raises:
        RuntimeError: If approval fails
    """
    result = approve_plan(task_id, approved_by=approved_by, notes=notes)

    if not result:
        try:
            task_data = task_store.get_task(task_id)
            if task_data:
                create_task_spirit(task_id=task_id)
                result = approve_plan(task_id, approved_by=approved_by, notes=notes)
        except Exception as e:
            logger.warning("Failed to create task_spirit for approval: %s", e)

    if not result:
        raise RuntimeError(f"Failed to approve plan for task {task_id}")

    return result


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

    # Get subtasks and summary needed for continuity output.
    subtasks = get_subtasks_for_task(task_id, include_steps=False)
    subtasks_with_steps = get_subtasks_for_task(task_id, include_steps=True)
    summary = get_subtask_summary(task_id)

    # Get blockers
    blockers = dep_store.get_blocking_tasks(task_id)
    progress_log = [
        f"[{e['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}] {e['message']}"
        for e in get_events_by_trace(task_id, visibility="user", limit=500)
        if e.get("message")
    ]
    continuity = build_continuity(
        task=task,
        spirit=spirit,
        subtasks=subtasks_with_steps,
        blockers=blockers,
        progress_log=progress_log,
        summary=summary,
    )

    lane_check = None if is_final_task_status(task.get("status")) else check_task_lane_conflicts(task_id, project_id)

    if format == "json":
        return build_context_json(task, spirit, subtasks, blockers, continuity, lane_check)

    # Default: TOON format
    readiness = None
    if not is_final_task_status(task.get("status")):
        readiness = assess_task_execution_readiness(task, spirit, subtasks_with_steps)
    return PlainTextResponse(
        content=format_toon_context(task, spirit, subtasks, blockers, continuity, readiness, lane_check)
    )


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
    subtasks = get_subtasks_for_task(task_id, include_steps=True)

    return build_export_data(task, spirit, subtasks)


@router.get("/tasks/{task_id}/export")
async def export_task_global(task_id: str) -> dict[str, Any]:
    """Export complete task data for plan.json round-trip without project scoping."""
    task = get_task_or_404(task_id)
    spirit = get_task_spirit(task_id)
    subtasks = get_subtasks_for_task(task_id, include_steps=True)
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
