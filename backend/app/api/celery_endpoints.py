"""Celery task monitoring endpoints for SummitFlow.

Provides REST API endpoints for inspecting Celery tasks:
- GET /api/tasks - Unified task list with filtering
- GET /api/tasks/queue - Queue depth and stats
- GET /api/tasks/schedule - Beat schedule information
- GET /api/workers - Worker status/stats
"""

from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.celery_app import celery_app
from app.services.celery_inspector import (
    get_queue_depth,
    get_unified_task_list,
    get_worker_stats,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


# Pydantic Models
class TaskInfo(BaseModel):
    """Information about a single Celery task."""

    id: str = Field(..., description="Task UUID")
    name: str = Field(..., description="Task name (module.function)")
    status: str = Field(..., description="Task status: ACTIVE, PENDING, SUCCESS, FAILURE")
    started_at: str | None = Field(None, description="ISO timestamp when task started")
    duration: float | None = Field(None, description="Task duration in seconds")
    worker: str | None = Field(None, description="Worker name (e.g., celery@hostname)")
    args: str | None = Field(None, description="JSON string of task arguments")
    kwargs: str | None = Field(None, description="JSON string of task keyword arguments")
    result: str | None = Field(None, description="Task result (completed tasks only)")
    traceback: str | None = Field(None, description="Error traceback (failed tasks only)")
    date_done: str | None = Field(None, description="ISO timestamp when task completed")


class TaskListResponse(BaseModel):
    """Response containing list of tasks with statistics."""

    tasks: list[TaskInfo] = Field(..., description="List of tasks")
    total: int = Field(..., description="Total number of tasks returned")
    active_count: int = Field(..., description="Count of active (running) tasks")
    pending_count: int = Field(..., description="Count of pending (queued) tasks")
    completed_count: int = Field(..., description="Count of completed tasks")
    failed_count: int = Field(..., description="Count of failed tasks")


class QueueInfo(BaseModel):
    """Queue depth and consumer information."""

    depth: int = Field(..., description="Number of tasks in queue")
    consumers: int = Field(..., description="Number of active workers")


class ScheduleInfo(BaseModel):
    """Celery Beat schedule information."""

    name: str = Field(..., description="Task name")
    task: str = Field(..., description="Full task path")
    schedule: str = Field(..., description="Schedule string")


class WorkerInfo(BaseModel):
    """Worker status information."""

    workers: int = Field(..., description="Number of active workers")
    details: dict[str, Any] = Field(default_factory=dict, description="Per-worker details")


# API Endpoints
@router.get("", response_model=TaskListResponse)
def get_tasks(
    status: Literal["all", "active", "pending", "completed", "failed"] = Query(
        "all", description="Filter tasks by status"
    ),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of tasks to return"),
) -> TaskListResponse:
    """Get unified list of Celery tasks with optional filtering.

    Args:
        status: Filter by task status (all, active, pending, completed, failed)
        limit: Maximum number of tasks to return (1-500)

    Returns:
        TaskListResponse with filtered tasks and statistics
    """
    tasks = get_unified_task_list(status=status, limit=limit)

    # Calculate statistics
    active_count = sum(1 for t in tasks if t.get("status") == "ACTIVE")
    pending_count = sum(1 for t in tasks if t.get("status") == "PENDING")
    completed_count = sum(1 for t in tasks if t.get("status") == "SUCCESS")
    failed_count = sum(1 for t in tasks if t.get("status") == "FAILURE")

    # Convert to Pydantic models
    task_infos = [TaskInfo(**task) for task in tasks]

    return TaskListResponse(
        tasks=task_infos,
        total=len(task_infos),
        active_count=active_count,
        pending_count=pending_count,
        completed_count=completed_count,
        failed_count=failed_count,
    )


@router.get("/queue", response_model=QueueInfo)
def get_queue() -> QueueInfo:
    """Get Celery queue depth and worker count.

    Returns:
        QueueInfo with current queue depth and active workers
    """
    depth = get_queue_depth()
    worker_stats = get_worker_stats()

    return QueueInfo(depth=depth, consumers=worker_stats["workers"])


@router.get("/schedule", response_model=list[ScheduleInfo])
def get_schedule() -> list[ScheduleInfo]:
    """Get Celery Beat schedule information.

    Returns:
        List of scheduled tasks with timing information
    """
    beat_schedule = celery_app.conf.beat_schedule

    if not beat_schedule:
        return []

    schedule_list: list[ScheduleInfo] = []
    for name, config in beat_schedule.items():
        schedule_seconds = config.get("schedule", 0)

        if isinstance(schedule_seconds, (int, float)):
            if schedule_seconds >= 86400:
                days = schedule_seconds / 86400
                schedule_str = f"every {days:.1f} day(s)"
            elif schedule_seconds >= 3600:
                hours = schedule_seconds / 3600
                schedule_str = f"every {hours:.1f} hour(s)"
            elif schedule_seconds >= 60:
                minutes = schedule_seconds / 60
                schedule_str = f"every {minutes:.1f} minute(s)"
            else:
                schedule_str = f"every {schedule_seconds:.1f} second(s)"
        else:
            schedule_str = str(schedule_seconds)

        schedule_info = ScheduleInfo(
            name=name,
            task=config.get("task", "unknown"),
            schedule=schedule_str,
        )
        schedule_list.append(schedule_info)

    return schedule_list


@router.get("/workers", response_model=WorkerInfo)
def get_workers() -> WorkerInfo:
    """Get Celery worker status.

    Returns:
        WorkerInfo with worker count and details
    """
    stats = get_worker_stats()
    return WorkerInfo(workers=stats["workers"], details=stats["details"])
