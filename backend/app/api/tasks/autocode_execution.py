"""Autocode execution logic.

Core execution helpers and state management for autocode operations.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from ...services.agent_hub import (
    AgentHubService,
    ExecutionState,
    TaskContext,
)
from ...storage.subtasks import get_subtasks_for_task

# In-memory execution state storage (for MVP, migrate to DB later)
_executions: dict[str, ExecutionState] = {}
_services: dict[str, AgentHubService] = {}


def get_first_incomplete_subtask(task_id: str) -> dict[str, Any] | None:
    """Get the first incomplete subtask for a task.

    Args:
        task_id: Task ID

    Returns:
        First incomplete subtask or None if all complete
    """
    subtasks = get_subtasks_for_task(task_id, include_steps=True)
    for subtask in subtasks:
        if not subtask.get("passes", False):
            return subtask
    return None


def build_task_context(
    task: dict[str, Any],
    subtask: dict[str, Any],
) -> TaskContext:
    """Build TaskContext for worker execution.

    Args:
        task: Task dict
        subtask: Subtask dict

    Returns:
        TaskContext for Agent Hub
    """
    steps = subtask.get("steps", [])
    step_dicts = [
        {"description": s.get("description", ""), "step_number": s.get("step_number", i + 1)}
        for i, s in enumerate(steps)
    ]

    # spirit_anti is a string, but constraints expects list[str]
    spirit_anti = task.get("spirit_anti")
    constraints = [spirit_anti] if spirit_anti else None

    return TaskContext(
        task_id=task["id"],
        subtask_id=subtask["subtask_id"],
        project_id=task["project_id"],
        description=subtask.get("description", ""),
        steps=step_dicts,
        objective=task.get("objective"),
        done_when=task.get("done_when"),
        constraints=constraints,
    )


def generate_execution_id() -> str:
    """Generate a unique execution ID.

    Returns:
        Execution ID string
    """
    return f"exec-{uuid.uuid4().hex[:12]}"


def get_or_create_service(
    project_id: str,
    agent_slug: str,
) -> AgentHubService:
    """Get or create Agent Hub service for project.

    Args:
        project_id: Project ID
        agent_slug: Agent Hub agent slug

    Returns:
        AgentHubService instance
    """
    if project_id not in _services:
        _services[project_id] = AgentHubService(project_id, agent_slug=agent_slug)
    return _services[project_id]


def create_execution_state(
    execution_id: str,
    task_id: str,
    subtask_id: str,
) -> ExecutionState:
    """Create and store execution state.

    Args:
        execution_id: Execution ID
        task_id: Task ID
        subtask_id: Subtask ID

    Returns:
        ExecutionState instance
    """
    state = ExecutionState(
        execution_id=execution_id,
        task_id=task_id,
        current_subtask_id=subtask_id,
        status="running",
        started_at=datetime.now(UTC),
    )
    _executions[execution_id] = state
    return state


def get_execution_state(execution_id: str) -> ExecutionState | None:
    """Get execution state by ID.

    Args:
        execution_id: Execution ID

    Returns:
        ExecutionState or None if not found
    """
    return _executions.get(execution_id)


def update_execution_completed(
    state: ExecutionState,
    evidence: Any,
) -> None:
    """Update execution state to completed.

    Args:
        state: ExecutionState to update
        evidence: Execution evidence
    """
    state.status = "completed" if evidence.status == "completed" else "failed"
    state.evidence = evidence
    state.completed_at = datetime.now(UTC)


def update_execution_failed(execution_id: str) -> None:
    """Mark execution as failed.

    Args:
        execution_id: Execution ID
    """
    if execution_id in _executions:
        _executions[execution_id].status = "failed"


def close_service(project_id: str) -> None:
    """Close and remove service for project.

    Args:
        project_id: Project ID
    """
    if project_id in _services:
        _services[project_id].close()
        del _services[project_id]
