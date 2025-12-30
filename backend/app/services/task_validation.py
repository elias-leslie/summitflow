"""Task validation service - Pre-work validation for tasks.

This module provides validation logic to check if a task is ready to be worked on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..storage import task_dependencies as dep_store
from ..storage import tasks as task_store


@dataclass
class TaskValidationResult:
    """Result of task readiness validation.

    Used for pre-work checks (dependencies, criteria, etc.)
    """

    ready: bool
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "ready": self.ready,
            "issues": self.issues,
            "suggestions": self.suggestions,
        }


# Alias for backward compatibility
ValidationResult = TaskValidationResult


def validate_task_ready(task_id: str, project_id: str) -> TaskValidationResult:
    """Validate if a task is ready to be worked on.

    Performs the following checks:
    1. Task exists and belongs to project
    2. Task is not already running or completed
    3. Task has no incomplete blocking dependencies

    Args:
        task_id: Task ID to validate
        project_id: Project ID the task should belong to

    Returns:
        ValidationResult with ready status, issues, and suggestions
    """
    issues: list[str] = []
    suggestions: list[str] = []

    # Check task exists
    task = task_store.get_task(task_id)
    if not task:
        return ValidationResult(
            ready=False,
            issues=[f"Task '{task_id}' not found"],
        )

    # Check task belongs to project
    if task["project_id"] != project_id:
        return ValidationResult(
            ready=False,
            issues=[f"Task '{task_id}' not found in project '{project_id}'"],
        )

    # Check task status
    status = task["status"]
    if status == "completed":
        return ValidationResult(
            ready=False,
            issues=["Task is already completed"],
        )
    if status == "running":
        return ValidationResult(
            ready=False,
            issues=["Task is already running"],
        )

    # Check for blocking dependencies
    blockers = dep_store.get_blocking_tasks(task_id)
    if blockers:
        blocker_list = ", ".join(f"{b['id']} ({b['status']})" for b in blockers)
        issues.append(f"Task is blocked by {len(blockers)} incomplete task(s): {blocker_list}")
        suggestions.append("Complete blocking tasks first or remove the dependencies")

    # Determine if ready
    ready = len(issues) == 0

    return ValidationResult(
        ready=ready,
        issues=issues,
        suggestions=suggestions,
    )
