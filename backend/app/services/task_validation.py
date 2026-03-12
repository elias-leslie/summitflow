"""Task validation service - Pre-work validation for tasks.

This module provides validation logic to check if a task is ready to be worked on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..storage import task_dependencies as dep_store
from ..storage import tasks as task_store
from .task_execution_readiness import load_task_execution_readiness
from .task_lane_preflight import check_task_lane_conflicts


@dataclass
class TaskValidationResult:
    """Result of task readiness validation.

    Used for pre-work checks (dependencies, criteria, etc.)
    """

    ready: bool
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    lane_conflict: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        result: dict[str, Any] = {
            "ready": self.ready,
            "issues": self.issues,
            "suggestions": self.suggestions,
        }
        if self.lane_conflict is not None:
            result["lane_conflict"] = self.lane_conflict
        return result



def _check_task_exists_in_project(
    task_id: str, project_id: str
) -> tuple[dict[str, Any] | None, TaskValidationResult | None]:
    """Return (task, None) when checks pass, or (None, failed_result) otherwise."""
    task = task_store.get_task(task_id)
    if not task:
        return None, TaskValidationResult(
            ready=False,
            issues=[f"Task '{task_id}' not found"],
        )
    if task["project_id"] != project_id:
        return None, TaskValidationResult(
            ready=False,
            issues=[f"Task '{task_id}' not found in project '{project_id}'"],
        )
    return task, None


def _check_task_status(task: dict[str, Any]) -> TaskValidationResult | None:
    """Return a failed TaskValidationResult if the task status prevents work.

    Returns None when the status allows the task to be started.
    """
    status = task["status"]
    if status == "completed":
        return TaskValidationResult(
            ready=False,
            issues=["Task is already completed"],
        )
    if status == "running":
        return TaskValidationResult(
            ready=False,
            issues=["Task is already running"],
        )
    return None


def _collect_blocker_issues(
    task_id: str,
    issues: list[str],
    suggestions: list[str],
) -> None:
    """Append blocker issues and suggestions in-place if blocking dependencies exist."""
    blockers = dep_store.get_blocking_tasks(task_id)
    if blockers:
        blocker_list = ", ".join(f"{b['id']} ({b['status']})" for b in blockers)
        issues.append(f"Task is blocked by {len(blockers)} incomplete task(s): {blocker_list}")
        suggestions.append("Complete blocking tasks first or remove the dependencies")


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
        TaskValidationResult with ready status, issues, and suggestions
    """
    task, early = _check_task_exists_in_project(task_id, project_id)
    if early is not None:
        return early

    status_result = _check_task_status(task)
    if status_result is not None:
        return status_result

    issues: list[str] = []
    suggestions: list[str] = []
    _collect_blocker_issues(task_id, issues, suggestions)
    lane_check = check_task_lane_conflicts(task_id, project_id)
    issues.extend(lane_check.issues)
    suggestions.extend(lane_check.suggestions)
    readiness = load_task_execution_readiness(task_id)
    issues.extend(readiness.issues)
    suggestions.extend(readiness.suggestions)

    lane_conflict = None
    if lane_check.disposition != "allow":
        lane_conflict = {
            "overlap_kind": lane_check.overlap_kind,
            "disposition": lane_check.disposition,
            "overlap_paths": lane_check.overlap_paths,
            "shared_plumbing": lane_check.shared_plumbing,
            "conflicting_tasks": lane_check.conflicting_tasks,
        }

    return TaskValidationResult(
        ready=len(issues) == 0,
        issues=issues,
        suggestions=suggestions,
        lane_conflict=lane_conflict,
    )
