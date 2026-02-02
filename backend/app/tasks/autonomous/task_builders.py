"""Task creation builders for autonomous task generation."""

from __future__ import annotations

import logging
from typing import Any

from app.services.task_issue_mapper import link_issue_to_task
from app.storage import qa_issues as qa_storage
from app.storage import tasks as task_store
from app.storage.steps import bulk_create_steps
from app.storage.subtasks import bulk_create_subtasks
from app.storage.task_spirit import approve_plan, create_task_spirit

logger = logging.getLogger(__name__)


def create_refactor_task(
    project_id: str,
    relative_path: str,
    file_path: str,
    reason: str,
    complexity: float,
    lines: int,
    target_lines: int,
    priority: str,
    tier: int,
    steps: list[dict[str, str]],
) -> tuple[str | None, int | None]:
    """Create a refactor task with spirit, subtasks, and steps.

    Args:
        project_id: Project ID
        relative_path: Relative file path for display
        file_path: Absolute file path for verification
        reason: Reason for refactoring
        complexity: Complexity score
        lines: Current line count
        target_lines: Target line count
        priority: Task priority (high/medium/low)
        tier: Model tier (1=Haiku, 2=Sonnet, 3=Opus)
        steps: List of step dictionaries

    Returns:
        Tuple of (task_id, issue_id) or (None, None) on error
    """
    title = f"Refactor: {reason} in {relative_path.split('/')[-1]}"
    description = (
        f"Auto-generated from Explorer scan.\n\n"
        f"File: {relative_path}\n"
        f"Lines: {lines} → target <{target_lines}\n"
        f"Complexity: {complexity:.1f}\n"
        f"Priority: {priority}"
    )

    # Create QA issue first (for self-healing linkage)
    issue_id = qa_storage.upsert_issue(
        project_id=project_id,
        issue_type="complexity",
        file_path=relative_path,
        title=f"High complexity in {relative_path.split('/')[-1]}",
        severity="high" if complexity > 15 else "medium",
        description=f"Complexity: {complexity:.1f}, Lines: {lines}",
        metadata={
            "complexity_score": complexity,
            "lines_of_code": lines,
            "target_lines": target_lines,
            "reason": reason,
        },
    )

    task = task_store.create_task(
        project_id=project_id,
        title=title,
        description=description,
        priority=2 if priority == "high" else 3,
        task_type="refactor",
        tier=tier,
    )

    if not task:
        return None, None

    task_id = task["id"]
    link_issue_to_task(issue_id, task_id)

    category = "backend" if relative_path.endswith(".py") else "frontend"

    # Create task_spirit
    objective = (
        f"Refactor {relative_path} to reduce line count from {lines} to <{target_lines} lines "
        f"while preserving all existing behavior."
    )
    done_when = [
        "All quality gates pass (ruff, mypy, pytest)",
        f"File line count reduced to <{target_lines} lines (current: {lines})",
        "No regressions - all existing tests pass",
    ]
    if category == "frontend":
        done_when.append("No console errors in browser")

    create_task_spirit(
        task_id=task_id,
        objective=objective,
        spirit_anti="Do NOT change external behavior. Do NOT rename public APIs without updating all callers.",
        done_when=done_when,
        complexity="SIMPLE",
    )
    approve_plan(task_id, approved_by="auto-generated")

    # Create subtask
    subtask_data = [
        {
            "subtask_id": "1.1",
            "phase": category,
            "description": f"Refactor {relative_path} - reduce to <{target_lines} lines",
        }
    ]
    created_subtasks = bulk_create_subtasks(task_id, subtask_data)

    # Create steps
    if created_subtasks:
        subtask_full_id = created_subtasks[0]["id"]
        bulk_create_steps(subtask_full_id, steps)

    logger.info(f"Created refactor task {task_id} with line verification: {title}")
    return task_id, issue_id


def create_schema_task(
    project_id: str,
    table_name: str,
    violation_type: str,
    detail: str,
    severity: str,
    metadata: dict[str, Any],
    steps: list[dict[str, str]],
    title: str,
    objective: str,
    done_when: list[str],
    tier: int,
) -> tuple[str | None, int | None]:
    """Create a schema task with spirit, subtasks, and steps.

    Returns:
        Tuple of (task_id, issue_id) or (None, None) on error
    """
    file_path = f"table:{table_name}"

    issue_id = qa_storage.upsert_issue(
        project_id=project_id,
        issue_type=violation_type,
        file_path=file_path,
        title=f"Schema: {detail}",
        severity="high" if severity == "error" else "medium",
        description=f"Table: {table_name}\nViolation: {detail}",
        metadata={
            "table_name": table_name,
            "violation_type": violation_type,
            **metadata,
        },
    )

    description = (
        f"Auto-generated from Explorer schema scan.\n\n"
        f"Table: {table_name}\n"
        f"Violation: {detail}\n"
        f"Severity: {severity}"
    )

    task = task_store.create_task(
        project_id=project_id,
        title=title,
        description=description,
        priority=2 if severity == "error" else 3,
        task_type="schema",
        tier=tier,
    )

    if not task:
        return None, None

    task_id = task["id"]
    link_issue_to_task(issue_id, task_id)

    create_task_spirit(
        task_id=task_id,
        objective=objective,
        spirit_anti="Do NOT break existing queries. Do NOT rename without updating all references.",
        done_when=done_when,
        complexity="SIMPLE",
    )
    approve_plan(task_id, approved_by="auto-generated")

    subtask_data = [
        {
            "subtask_id": "1.1",
            "phase": "backend",
            "description": f"Fix {violation_type} in {table_name}",
        }
    ]
    created_subtasks = bulk_create_subtasks(task_id, subtask_data)

    if created_subtasks:
        subtask_full_id = created_subtasks[0]["id"]
        bulk_create_steps(subtask_full_id, steps)

    logger.info(f"Created schema task {task_id}, linked to issue {issue_id}: {title}")
    return task_id, issue_id


def create_architecture_task(
    project_id: str,
    violation_type: str,
    violations: list[dict[str, Any]],
    affected_files: list[str],
    title: str,
    severity: str,
    tier: int,
    objective: str,
    done_when: list[str],
    complexity: str,
    auto_approve: bool,
) -> tuple[str | None, int | None]:
    """Create an architecture task with spirit, subtasks, and steps.

    Returns:
        Tuple of (task_id, issue_id) or (None, None) on error
    """
    issue_path = f"architecture:{violation_type}"

    issue_id = qa_storage.upsert_issue(
        project_id=project_id,
        issue_type=violation_type,
        file_path=issue_path,
        title=f"Architecture: {title}",
        severity="high" if severity == "error" else "medium",
        description=f"Found {len(violations)} {violation_type} violations across {len(affected_files)} files",
        metadata={
            "violation_type": violation_type,
            "affected_files": affected_files[:20],
            "violation_count": len(violations),
        },
    )

    description = (
        f"Auto-generated from Explorer architecture scan.\n\n"
        f"**Violation Type:** {violation_type.replace('_', ' ').title()}\n"
        f"**Affected Files:** {len(affected_files)}\n"
        f"**Total Violations:** {len(violations)}\n\n"
        f"### Files to fix:\n"
    )
    for f in affected_files[:15]:
        description += f"- {f}\n"
    if len(affected_files) > 15:
        description += f"- ... and {len(affected_files) - 15} more files\n"

    task = task_store.create_task(
        project_id=project_id,
        title=f"Architecture: {title}",
        description=description,
        priority=2 if severity == "error" else 3,
        task_type="refactor",
        tier=tier,
    )

    if not task:
        return None, None

    task_id = task["id"]
    link_issue_to_task(issue_id, task_id)

    create_task_spirit(
        task_id=task_id,
        objective=objective,
        spirit_anti="Do NOT break existing functionality. Fix violations systematically, not file-by-file randomly.",
        done_when=done_when,
        complexity=complexity,
    )

    if auto_approve:
        approve_plan(task_id, approved_by="auto-generated")

    # Create subtasks for affected files
    subtask_data = []
    for i, file_path in enumerate(affected_files[:10], 1):
        subtask_data.append(
            {
                "subtask_id": f"1.{i}",
                "phase": "backend" if file_path.endswith(".py") else "frontend",
                "description": f"Fix {violation_type.replace('_', ' ')} in {file_path.split('/')[-1]}",
            }
        )

    if subtask_data:
        created_subtasks = bulk_create_subtasks(task_id, subtask_data)

        for subtask in created_subtasks:
            subtask_full_id = subtask["id"]
            steps = [
                {"description": f"Identify {violation_type.replace('_', ' ')} issue"},
                {"description": "Implement fix following project patterns"},
                {"description": "Verify fix with tests or manual check"},
            ]
            bulk_create_steps(subtask_full_id, steps)

    logger.info(
        f"Created consolidated architecture task {task_id} for {violation_type}: "
        f"{len(affected_files)} files, linked to issue {issue_id}"
    )
    return task_id, issue_id
