"""Tasks API - Subtask and step helper functions.

Shared logic for subtask and step endpoints to reduce duplication.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ...schemas.tasks import SubtaskCreate, SubtaskResponse, SubtaskUpdate


def get_subtask_table_id(task_id: str, subtask_id: str) -> str:
    """Generate the subtask table ID.

    Format: {task_id}-{subtask_id} e.g., "task-abc123-1.1"

    Args:
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")

    Returns:
        Subtask table ID string
    """
    return f"{task_id}-{subtask_id}"


def get_verification_cwd(project_id: str, task_id: str) -> str | None:
    """Get the working directory for step verification.

    If a worktree exists for the task, returns the worktree path.
    Otherwise returns the project root path.

    Args:
        project_id: Project ID
        task_id: Task ID (used to check for worktree isolation)

    Returns:
        Path to use as cwd for verification commands
    """
    from cli.lib.worktree import get_worktree_info

    from ...storage.projects import get_project_root_path

    if task_id:
        worktree_info = get_worktree_info(task_id, project_id)
        if worktree_info and worktree_info.path.exists():
            return str(worktree_info.path)

    return get_project_root_path(project_id)


def convert_steps_to_storage_format(steps: list[Any]) -> list[str | dict[str, Any]]:
    """Convert StepInput objects to dicts for storage layer.

    Args:
        steps: List of steps (strings or StepInput objects)

    Returns:
        List of steps in storage format (strings or dicts)
    """
    result: list[str | dict[str, Any]] = []
    for step in steps:
        if isinstance(step, str):
            result.append(step)
        else:
            step_dict: dict[str, Any] = {"description": step.description}
            if step.spec:
                step_dict["spec"] = step.spec
            result.append(step_dict)
    return result


def convert_steps_to_response_format(subtask: dict[str, Any]) -> dict[str, Any]:
    """Convert subtask steps from storage format to response format.

    Args:
        subtask: Subtask dict from storage layer

    Returns:
        Subtask dict with steps in response format
    """
    if subtask.get("steps") and isinstance(subtask["steps"][0], dict):
        subtask["steps"] = [
            s.get("description", "") for s in subtask["steps"] if isinstance(s, dict)
        ]
    elif "steps" not in subtask:
        subtask["steps"] = []
    return subtask


def ensure_steps_field(subtask: dict[str, Any]) -> dict[str, Any]:
    """Ensure subtask dict has a steps field.

    Args:
        subtask: Subtask dict

    Returns:
        Subtask dict with steps field
    """
    if "steps" not in subtask:
        subtask["steps"] = []
    return subtask


def get_subtasks_with_summary(task_id: str, include_steps: bool) -> dict[str, Any]:
    """Get subtasks and summary for a task.

    Args:
        task_id: Task ID
        include_steps: If True, include steps for each subtask

    Returns:
        Dict with subtasks list and summary
    """
    from ...storage.subtasks import get_subtask_summary, get_subtasks_for_task

    subtasks = get_subtasks_for_task(task_id, include_steps=include_steps)
    summary = get_subtask_summary(task_id)

    return {
        "subtasks": subtasks,
        "summary": summary,
    }


def update_subtask_logic(
    task_id: str,
    subtask_id: str,
    request: SubtaskUpdate,
) -> SubtaskResponse:
    """Update a subtask's passes status.

    Args:
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")
        request: Update with passes boolean

    Returns:
        Updated SubtaskResponse

    Raises:
        HTTPException: If subtask not found or gate conditions not met
    """
    from ...storage.subtasks import update_subtask_passes
    from ...storage.subtasks_validation import SubtaskGateError

    try:
        updated = update_subtask_passes(task_id, subtask_id, request.passes)
    except SubtaskGateError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(e),
                "incomplete_steps": e.incomplete_steps,
            },
        ) from e

    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Subtask {subtask_id} not found for task {task_id}",
        )

    ensure_steps_field(updated)
    return SubtaskResponse(**updated)


def create_subtask_logic(
    task_id: str,
    request: SubtaskCreate,
) -> SubtaskResponse:
    """Create a single subtask for a task.

    Args:
        task_id: Task ID
        request: Subtask creation data

    Returns:
        Created SubtaskResponse
    """
    from ...storage.subtask_dependencies import CycleError
    from ...storage.subtasks import (
        add_subtask_dependency,
        create_subtask,
        delete_subtask,
        get_subtask,
    )

    steps = convert_steps_to_storage_format(request.steps)
    depends_on = [str(dep).strip() for dep in (request.depends_on or []) if str(dep).strip()]
    for dependency_id in depends_on:
        if dependency_id == request.subtask_id:
            raise ValueError("Subtask cannot depend on itself")
        if get_subtask(task_id, dependency_id) is None:
            raise ValueError(f"Dependency subtask {dependency_id} not found for task {task_id}")

    subtask = create_subtask(
        task_id=task_id,
        subtask_id=request.subtask_id,
        description=request.description,
        display_order=request.display_order,
        phase=request.phase,
        steps=steps,
        depends_on=depends_on,
        subtask_type=request.subtask_type,
    )
    try:
        for dependency_id in depends_on:
            add_subtask_dependency(task_id, request.subtask_id, dependency_id)
    except CycleError as e:
        delete_subtask(task_id, request.subtask_id)
        raise ValueError(str(e)) from e

    subtask["depends_on"] = depends_on
    convert_steps_to_response_format(subtask)
    return SubtaskResponse(**subtask)


def delete_subtask_logic(
    project_id: str,
    task_id: str,
    subtask_id: str,
) -> dict[str, Any]:
    """Delete a subtask and all its steps.

    Args:
        project_id: Project ID
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "99.1")

    Returns:
        Deletion confirmation with details

    Raises:
        HTTPException: If subtask not found
    """
    from ...storage.subtasks import delete_subtask

    deleted = delete_subtask(task_id, subtask_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Subtask {subtask_id} not found for task {task_id}",
        )

    return {
        "status": "deleted",
        "project_id": project_id,
        "task_id": task_id,
        "subtask_id": subtask_id,
    }
