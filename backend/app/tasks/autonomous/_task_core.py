"""Core task creation utilities."""

from __future__ import annotations

import logging
from typing import cast

from app.services.task_issue_mapper import link_issue_to_task
from app.storage import tasks as task_store
from app.storage.task_spirit import approve_plan, create_task_spirit

logger = logging.getLogger(__name__)


def create_task_with_spirit(
    project_id: str,
    title: str,
    description: str,
    priority: int,
    task_type: str,
    tier: int,
    objective: str,
    spirit_anti: str,
    done_when: list[str],
    complexity: str,
    auto_approve: bool = True,
) -> str | None:
    """Create a task with spirit.

    Args:
        project_id: Project ID
        title: Task title
        description: Task description
        priority: Task priority (2=high, 3=medium)
        task_type: Task type
        tier: Model tier (1=Haiku, 2=Sonnet, 3=Opus)
        objective: Spirit objective
        spirit_anti: Spirit anti-pattern
        done_when: List of completion criteria
        complexity: Complexity level (SIMPLE/MODERATE/COMPLEX)
        auto_approve: Whether to auto-approve the plan

    Returns:
        Task ID or None if creation failed
    """
    task = task_store.create_task(
        project_id=project_id,
        title=title,
        description=description,
        priority=priority,
        task_type=task_type,
        tier=tier,
    )

    if not task:
        return None

    task_id = cast(str, task["id"])

    create_task_spirit(
        task_id=task_id,
        objective=objective,
        spirit_anti=spirit_anti,
        done_when=done_when,
        complexity=complexity,
    )

    if auto_approve:
        approve_plan(task_id, approved_by="auto-generated")

    return task_id


def link_task_to_issue(task_id: str, issue_id: int) -> None:
    """Link a task to a QA issue.

    Args:
        task_id: Task ID
        issue_id: Issue ID
    """
    link_issue_to_task(issue_id, task_id)


def build_refactor_description(
    relative_path: str,
    lines: int,
    target_lines: int,
    complexity: float,
    priority: str,
) -> str:
    """Build description for refactor task.

    Args:
        relative_path: Relative file path
        lines: Current line count
        target_lines: Target line count
        complexity: Complexity score
        priority: Task priority

    Returns:
        Task description
    """
    return (
        f"Auto-generated from Explorer scan.\n\n"
        f"File: {relative_path}\n"
        f"Lines: {lines} → target <{target_lines}\n"
        f"Complexity: {complexity:.1f}\n"
        f"Priority: {priority}"
    )


def build_architecture_description(
    violation_type: str,
    affected_files: list[str],
    violations_count: int,
) -> str:
    """Build description for architecture task.

    Args:
        violation_type: Type of violation
        affected_files: List of affected files
        violations_count: Number of violations

    Returns:
        Task description
    """
    description = (
        f"Auto-generated from Explorer architecture scan.\n\n"
        f"**Violation Type:** {violation_type.replace('_', ' ').title()}\n"
        f"**Affected Files:** {len(affected_files)}\n"
        f"**Total Violations:** {violations_count}\n\n"
        f"### Files to fix:\n"
    )
    for f in affected_files[:15]:
        description += f"- {f}\n"
    if len(affected_files) > 15:
        description += f"- ... and {len(affected_files) - 15} more files\n"
    return description
