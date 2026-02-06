"""Tasks API - Dependency management.

Handles:
- get_task_dependencies
- add_task_dependency
- remove_task_dependency
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ...schemas.tasks import DependencyCreate, DependencyResponse
from ...storage import task_dependencies as dep_store
from ...storage import tasks as task_store
from .helpers import get_task_or_404, verify_task_project

router = APIRouter()


@router.get(
    "/projects/{project_id}/tasks/{task_id}/dependencies", response_model=list[DependencyResponse]
)
async def get_task_dependencies(project_id: str, task_id: str) -> list[DependencyResponse]:
    """Get dependencies for a task (what this task depends on).

    Args:
        project_id: Project ID
        task_id: Task ID

    Returns:
        List of dependencies with details about the blocking tasks.
    """
    verify_task_project(task_id, project_id)

    deps = dep_store.get_dependencies(task_id)
    return [
        DependencyResponse(
            id=d["id"],
            task_id=d["task_id"],
            depends_on_task_id=d["depends_on_task_id"],
            dependency_type=d["dependency_type"],
            created_at=d["created_at"].isoformat() if d["created_at"] else None,
            depends_on_title=d.get("depends_on_title"),
            depends_on_status=d.get("depends_on_status"),
        )
        for d in deps
    ]


@router.post(
    "/projects/{project_id}/tasks/{task_id}/dependencies", response_model=DependencyResponse
)
async def add_task_dependency(
    project_id: str, task_id: str, dep: DependencyCreate
) -> DependencyResponse:
    """Add a dependency to a task.

    Args:
        project_id: Project ID
        task_id: Task ID (the task that depends on another)
        dep: Dependency details (depends_on_task_id, dependency_type)

    Returns:
        The created dependency.
    """
    verify_task_project(task_id, project_id)

    # Verify target task exists
    target = task_store.get_task(dep.depends_on_task_id)
    if not target:
        raise HTTPException(
            status_code=404, detail=f"Target task {dep.depends_on_task_id} not found"
        )

    try:
        created = dep_store.add_dependency(
            task_id=task_id,
            depends_on_task_id=dep.depends_on_task_id,
            dependency_type=dep.dependency_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not created:
        raise HTTPException(status_code=400, detail="Failed to create dependency")

    return DependencyResponse(
        id=created["id"],
        task_id=created["task_id"],
        depends_on_task_id=created["depends_on_task_id"],
        dependency_type=created["dependency_type"],
        created_at=created["created_at"].isoformat() if created["created_at"] else None,
    )


@router.delete(
    "/projects/{project_id}/tasks/{task_id}/dependencies/{depends_on_task_id}",
    response_model=dict[str, Any],
)
async def remove_task_dependency(
    project_id: str,
    task_id: str,
    depends_on_task_id: str,
    dependency_type: str | None = Query(None, description="Type to remove (all if not specified)"),
) -> dict[str, Any]:
    """Remove a dependency from a task.

    Args:
        project_id: Project ID
        task_id: Task ID
        depends_on_task_id: ID of the task being depended on
        dependency_type: Optional type filter (removes all types if not specified)

    Returns:
        Status dict.
    """
    verify_task_project(task_id, project_id)

    removed = dep_store.remove_dependency(task_id, depends_on_task_id, dependency_type)

    return {
        "status": "removed" if removed else "not_found",
        "task_id": task_id,
        "depends_on_task_id": depends_on_task_id,
        "dependency_type": dependency_type,
    }


# Global endpoints (no project_id required - task IDs are globally unique)


@router.get("/tasks/{task_id}/dependencies", response_model=list[DependencyResponse])
async def get_task_dependencies_global(task_id: str) -> list[DependencyResponse]:
    """Get dependencies for a task (global lookup, no project context required).

    Task IDs are globally unique, so project_id is not needed.

    Args:
        task_id: Task ID

    Returns:
        List of dependencies with details about the blocking tasks.
    """
    get_task_or_404(task_id)

    deps = dep_store.get_dependencies(task_id)
    return [
        DependencyResponse(
            id=d["id"],
            task_id=d["task_id"],
            depends_on_task_id=d["depends_on_task_id"],
            dependency_type=d["dependency_type"],
            created_at=d["created_at"].isoformat() if d["created_at"] else None,
            depends_on_title=d.get("depends_on_title"),
            depends_on_status=d.get("depends_on_status"),
        )
        for d in deps
    ]
