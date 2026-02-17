"""FastAPI dependency injection for common validations.

Provides reusable dependencies for validating projects and tasks.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Path

from ..storage import tasks as task_store
from ..storage.connection import get_connection


def get_valid_project(
    project_id: Annotated[str, Path(description="Project ID")],
) -> dict[str, Any]:
    """Validate that a project exists and return its data.

    Use as a FastAPI dependency to validate project_id path parameters.

    Args:
        project_id: Project ID from path parameter

    Returns:
        Project dict with id, name, base_url, health_endpoint, root_path, created_at

    Raises:
        HTTPException(404): If project not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, base_url, health_endpoint, root_path, created_at
            FROM projects
            WHERE id = %s
            """,
            (project_id,),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    return {
        "id": row[0],
        "name": row[1],
        "base_url": row[2],
        "health_endpoint": row[3],
        "root_path": row[4],
        "created_at": row[5],
    }


def validate_project_exists(project_id: str) -> None:
    """Validate that a project exists, raising 404 if not.

    Lightweight check that doesn't fetch project data.
    Use get_valid_project() instead if you need the project record.

    Args:
        project_id: Project ID to validate

    Raises:
        HTTPException: 404 if project not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")


def get_valid_task(
    task_id: Annotated[str, Path(description="Task ID")],
) -> dict[str, Any]:
    """Validate that a task exists and return its data.

    Use as a FastAPI dependency to validate task_id path parameters.
    Task IDs are globally unique, so project context is not required.

    Args:
        task_id: Task ID from path parameter

    Returns:
        Task dict from storage

    Raises:
        HTTPException(404): If task not found
    """
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


def get_valid_task_in_project(
    project_id: Annotated[str, Path(description="Project ID")],
    task_id: Annotated[str, Path(description="Task ID")],
) -> dict[str, Any]:
    """Validate that a task exists and belongs to the specified project.

    Use as a FastAPI dependency when both project_id and task_id are in path.

    Args:
        project_id: Project ID from path parameter
        task_id: Task ID from path parameter

    Returns:
        Task dict from storage

    Raises:
        HTTPException(404): If task not found or belongs to different project
    """
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Task {task_id} not found in project {project_id}"
        )
    return task


# Type aliases for cleaner dependency injection
ValidProject = Annotated[dict[str, Any], Depends(get_valid_project)]
ValidTask = Annotated[dict[str, Any], Depends(get_valid_task)]
ValidTaskInProject = Annotated[dict[str, Any], Depends(get_valid_task_in_project)]
