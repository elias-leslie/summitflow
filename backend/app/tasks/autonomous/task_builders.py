"""Task creation builders for autonomous task generation."""

from __future__ import annotations

from typing import Any

from app.tasks.autonomous._issue_builder import (
    create_architecture_issue,
    create_refactor_issue,
    create_schema_issue,
)
from app.tasks.autonomous._subtask_builder import (
    create_architecture_subtasks,
    create_single_subtask_with_steps,
)
from app.tasks.autonomous._task_core import (
    _build_issue_aware_done_when,
    _build_issue_aware_objective,
    build_refactor_description,
    create_task_with_spirit,
    link_task_to_issue,
)
from app.tasks.autonomous.upkeep_constants import (
    EXECUTION_MODE_AUTONOMOUS,
    SOURCE_REFACTORS,
    UPKEEP_LABELS,
)

from ...logging_config import get_logger

logger = get_logger(__name__)

__all__ = [
    "_build_issue_aware_done_when",
    "_build_issue_aware_objective",
    "build_refactor_description",
    "create_architecture_task",
    "create_refactor_task",
    "create_schema_task",
]



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
    steps: list[dict[str, object]],
    refactor_issues: list[str] | None = None,
    promotion_reasons: list[str] | None = None,
    promotion_confidence: str | None = None,
    issue_id: int | None = None,
) -> tuple[str | None, int | None]:
    """Create refactor task with spirit, subtasks, and steps."""
    issues = refactor_issues or []
    category = "backend" if relative_path.endswith(".py") else "frontend"
    title = f"Refactor: {relative_path} ({reason})"
    issue_id = issue_id or create_refactor_issue(
        project_id,
        relative_path,
        complexity,
        lines,
        target_lines,
        reason,
    )

    objective = _build_issue_aware_objective(relative_path, lines, target_lines, issues)
    task_id = create_task_with_spirit(
        project_id=project_id, title=title, description=objective,
        priority=2 if priority == "high" else 3, task_type="refactor", tier=tier,
        done_when=_build_issue_aware_done_when(lines, target_lines, issues, is_frontend=(category == "frontend")),
        context={
            "files_to_modify": [relative_path],
            "upkeep": {
                "source_key": f"upkeep:{SOURCE_REFACTORS}:{relative_path}",
                "signal_type": SOURCE_REFACTORS,
            },
        },
        complexity="SIMPLE", auto_approve=True, ai_review=False,
        execution_mode=EXECUTION_MODE_AUTONOMOUS,
        autonomous=True,
        labels=[*UPKEEP_LABELS, SOURCE_REFACTORS],
    )

    if not task_id:
        return None, None

    link_task_to_issue(task_id, issue_id)
    create_single_subtask_with_steps(
        task_id=task_id, subtask_id="1.1", phase=category,
        description=f"Refactor {relative_path} - simplify structure; reduce size toward <{target_lines} lines only if it improves clarity", steps=steps,
        subtask_type="refactor",
    )
    logger.info("Created refactor task %s with line verification: %s", task_id, title)
    return task_id, issue_id


def create_schema_task(
    project_id: str,
    table_name: str,
    violation_type: str,
    detail: str,
    severity: str,
    metadata: dict[str, Any],
    steps: list[dict[str, object]],
    title: str,
    objective: str,
    done_when: list[str],
    tier: int,
) -> tuple[str | None, int | None]:
    """Create schema task with spirit, subtasks, and steps."""
    issue_id = create_schema_issue(project_id, table_name, violation_type, detail, severity, metadata)

    task_id = create_task_with_spirit(
        project_id=project_id, title=title, description=objective,
        priority=2 if severity == "error" else 3, task_type="debt", tier=tier,
        done_when=done_when, complexity="SIMPLE", auto_approve=True,
    )

    if not task_id:
        return None, None

    link_task_to_issue(task_id, issue_id)
    create_single_subtask_with_steps(
        task_id=task_id, subtask_id="1.1", phase="backend",
        description=f"Fix {violation_type} in {table_name}", steps=steps,
    )
    logger.info("Created schema task %s, linked to issue %s: %s", task_id, issue_id, title)
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
    """Create architecture task with spirit, subtasks, and steps."""
    issue_id = create_architecture_issue(project_id, violation_type, title, severity, len(violations), affected_files)

    task_id = create_task_with_spirit(
        project_id=project_id, title=f"Architecture: {title}", description=objective,
        priority=2 if severity == "error" else 3, task_type="refactor", tier=tier,
        done_when=done_when, complexity=complexity, auto_approve=auto_approve,
    )

    if not task_id:
        return None, None

    link_task_to_issue(task_id, issue_id)
    create_architecture_subtasks(task_id, violation_type, affected_files)
    logger.info("Created consolidated architecture task %s for %s: %d files, linked to issue %s", task_id, violation_type, len(affected_files), issue_id)
    return task_id, issue_id
