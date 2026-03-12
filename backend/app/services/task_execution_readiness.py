"""Execution-readiness evaluation for agent-operated tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..storage import tasks as task_store
from ..storage.subtasks import get_subtasks_for_task
from ..storage.task_spirit import approve_plan, get_task_spirit, set_plan_status
from .task_second_opinion import assess_second_opinion_readiness

_NONTRIVIAL_TASK_TYPES = {"feature", "task", "refactor", "debt", "regression"}


def _has_scope_context(context: dict[str, Any] | None) -> bool:
    if not isinstance(context, dict):
        return False
    for key in ("files_to_modify", "files_to_create"):
        value = context.get(key)
        if isinstance(value, list) and any(str(item).strip() for item in value):
            return True
    return False


@dataclass
class TaskExecutionReadiness:
    """Execution-readiness evaluation for a task."""

    ready: bool
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    plan_status: str = "draft"


def _get_complexity(task: dict[str, Any], spirit: dict[str, Any] | None) -> str:
    return str(task.get("complexity") or (spirit or {}).get("complexity") or "SIMPLE")


def _steps_for_subtask(subtask: dict[str, Any]) -> list[dict[str, Any]]:
    steps = subtask.get("steps_from_table") or subtask.get("steps") or []
    return steps if isinstance(steps, list) else []


def _requires_nontrivial_plan(task: dict[str, Any], complexity: str) -> bool:
    return complexity in {"STANDARD", "COMPLEX"} or task.get("task_type") in _NONTRIVIAL_TASK_TYPES


def assess_task_execution_readiness(
    task: dict[str, Any],
    spirit: dict[str, Any] | None = None,
    subtasks: list[dict[str, Any]] | None = None,
) -> TaskExecutionReadiness:
    """Assess whether a task is ready for agent execution."""
    spirit = spirit or {}
    subtasks = subtasks or []
    complexity = _get_complexity(task, spirit)
    requires_nontrivial_plan = _requires_nontrivial_plan(task, complexity)

    issues: list[str] = []
    suggestions: list[str] = []
    missing_fields: list[str] = []

    objective = str(spirit.get("objective") or task.get("objective") or "").strip()
    done_when = spirit.get("done_when") or task.get("done_when") or []
    spirit_anti = str(spirit.get("spirit_anti") or task.get("spirit_anti") or "").strip()
    decisions = spirit.get("decisions") or task.get("decisions") or []
    context = spirit.get("context") or task.get("context") or {}

    if not objective:
        issues.append("Missing objective")
        missing_fields.append("objective")

    if not done_when:
        issues.append("Missing done_when success criteria")
        missing_fields.append("done_when")

    if requires_nontrivial_plan and not spirit_anti:
        issues.append("Missing spirit_anti guidance for non-trivial coding work")
        missing_fields.append("spirit_anti")

    if complexity == "COMPLEX" and not decisions:
        issues.append("Missing decisions for COMPLEX task")
        missing_fields.append("decisions")

    if requires_nontrivial_plan and not subtasks:
        issues.append("Missing subtasks for non-trivial coding work")
        missing_fields.append("subtasks")

    if subtasks and requires_nontrivial_plan:
        step_less = [
            subtask.get("subtask_id", "?")
            for subtask in subtasks
            if not _steps_for_subtask(subtask)
        ]
        if step_less:
            issues.append(
                "Missing step guidance for subtask(s): " + ", ".join(step_less[:5])
            )
            missing_fields.append("steps")

    if requires_nontrivial_plan and not _has_scope_context(context):
        issues.append("Missing execution scope context (files_to_modify/files_to_create)")
        missing_fields.append("context")

    if requires_nontrivial_plan and not task.get("description"):
        suggestions.append("Add a task description with scope and constraints")

    second_opinion_issues, second_opinion_suggestions, second_opinion_missing = (
        assess_second_opinion_readiness(task, spirit)
    )
    issues.extend(second_opinion_issues)
    suggestions.extend(second_opinion_suggestions)
    missing_fields.extend(second_opinion_missing)

    return TaskExecutionReadiness(
        ready=not issues,
        issues=issues,
        suggestions=suggestions,
        missing_fields=missing_fields,
        plan_status="approved" if not issues else "draft",
    )


def load_task_execution_readiness(task_id: str) -> TaskExecutionReadiness:
    """Load task data and evaluate execution readiness."""
    task = task_store.get_task(task_id)
    if not task:
        return TaskExecutionReadiness(ready=False, issues=[f"Task {task_id} not found"])
    spirit = get_task_spirit(task_id)
    subtasks = get_subtasks_for_task(task_id, include_steps=True)
    return assess_task_execution_readiness(task, spirit, subtasks)


def sync_task_execution_readiness(task_id: str, approved_by: str = "system") -> TaskExecutionReadiness:
    """Sync plan_status with the task's actual execution readiness."""
    task = task_store.get_task(task_id)
    if not task:
        return TaskExecutionReadiness(ready=False, issues=[f"Task {task_id} not found"])

    spirit = get_task_spirit(task_id)
    subtasks = get_subtasks_for_task(task_id, include_steps=True)
    readiness = assess_task_execution_readiness(task, spirit, subtasks)

    if spirit is None:
        return readiness

    current_status = spirit.get("plan_status") or "draft"
    if readiness.ready and current_status != "approved":
        approve_plan(task_id, approved_by=approved_by, notes="Auto-approved: execution-ready task")
    elif not readiness.ready and current_status != "draft":
        set_plan_status(task_id, "draft", notes="Auto-downgraded: execution details incomplete")

    return readiness
