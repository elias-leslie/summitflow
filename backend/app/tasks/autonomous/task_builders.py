"""Task creation builders for autonomous task generation."""

from __future__ import annotations

import logging
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
    build_architecture_description,
    build_refactor_description,
    create_task_with_spirit,
    link_task_to_issue,
)

logger = logging.getLogger(__name__)


_ISSUE_LABELS: dict[str, str] = {
    "high_complexity": "high cyclomatic complexity",
    "medium_complexity": "elevated complexity",
    "oversized": "oversized file (>500 LOC)",
    "large_file": "large file (>300 LOC)",
    "bloat_critical": "critical file bloat",
    "bloat_warning": "file bloat",
    "too_many_functions": "too many functions (>20)",
    "too_many_classes": "too many classes (>5)",
    "too_many_imports": "too many imports (>30)",
    "has_long_functions": "functions exceeding 50 lines",
    "has_large_classes": "classes with >10 methods",
    "deep_nesting": "nesting deeper than 3 levels",
    "magic_strings": "hardcoded magic strings",
    "stale_todos": "stale TODO/FIXME comments",
    "deprecated_code": "deprecated code markers",
    "legacy_code": "legacy variable naming",
}


def _build_issue_aware_objective(
    relative_path: str,
    lines: int,
    target_lines: int,
    refactor_issues: list[str],
) -> str:
    """Build task objective from actual issues, not just line count."""
    parts = [f"Refactor {relative_path}"]

    has_size_issue = any(i in refactor_issues for i in ("oversized", "large_file", "bloat_critical", "bloat_warning"))
    if has_size_issue:
        parts.append(f"to reduce from {lines} to <{target_lines} lines")

    structural = [i for i in refactor_issues if i not in ("oversized", "large_file", "bloat_critical", "bloat_warning", "high_complexity", "medium_complexity")]
    if structural:
        labels = [_ISSUE_LABELS.get(i, i.replace("_", " ")) for i in structural[:4]]
        parts.append(f"resolving: {', '.join(labels)}")

    parts.append("while preserving all existing behavior")
    return " — ".join(parts) + "."


def _build_issue_aware_done_when(
    lines: int,
    target_lines: int,
    refactor_issues: list[str],
    is_frontend: bool,
) -> list[str]:
    """Build done_when criteria from actual issues."""
    criteria = ["All quality gates pass (ruff, types, pytest)"]

    has_size_issue = any(i in refactor_issues for i in ("oversized", "large_file", "bloat_critical", "bloat_warning"))
    if has_size_issue:
        criteria.append(f"File line count reduced to <{target_lines} lines (current: {lines})")

    if "has_long_functions" in refactor_issues:
        criteria.append("No functions exceed 50 lines")
    if "deep_nesting" in refactor_issues:
        criteria.append("No nesting deeper than 3 levels")
    if "too_many_functions" in refactor_issues:
        criteria.append("Functions per file reduced to <=20")
    if "too_many_classes" in refactor_issues:
        criteria.append("Classes per file reduced to <=5")
    if "has_large_classes" in refactor_issues:
        criteria.append("No class has more than 10 methods")
    if "magic_strings" in refactor_issues:
        criteria.append("Magic strings extracted to constants or config")
    if "too_many_imports" in refactor_issues:
        criteria.append("Imports reduced to <=30")

    criteria.append("No regressions - all existing tests pass")

    if is_frontend:
        criteria.append("No console errors in browser")

    return criteria


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
    refactor_issues: list[str] | None = None,
) -> tuple[str | None, int | None]:
    """Create refactor task with spirit, subtasks, and steps."""
    issues = refactor_issues or []
    file_name = relative_path.split("/")[-1]
    title = f"Refactor: {reason} in {file_name}"
    description = build_refactor_description(relative_path, lines, target_lines, complexity, priority)

    issue_id = create_refactor_issue(project_id, relative_path, complexity, lines, target_lines, reason)

    objective = _build_issue_aware_objective(relative_path, lines, target_lines, issues)

    category = "backend" if relative_path.endswith(".py") else "frontend"
    done_when = _build_issue_aware_done_when(lines, target_lines, issues, is_frontend=(category == "frontend"))

    task_id = create_task_with_spirit(
        project_id=project_id,
        title=title,
        description=description,
        priority=2 if priority == "high" else 3,
        task_type="refactor",
        tier=tier,
        objective=objective,
        spirit_anti="Do NOT change external behavior. Do NOT rename public APIs without updating all callers.",
        done_when=done_when,
        complexity="SIMPLE",
        auto_approve=True,
        ai_review=False,
    )

    if not task_id:
        return None, None

    link_task_to_issue(task_id, issue_id)
    create_single_subtask_with_steps(
        task_id=task_id,
        subtask_id="1.1",
        phase=category,
        description=f"Refactor {relative_path} - reduce to <{target_lines} lines",
        steps=steps,
    )

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
    """Create schema task with spirit, subtasks, and steps."""
    issue_id = create_schema_issue(project_id, table_name, violation_type, detail, severity, metadata)

    description = f"Auto-generated from Explorer schema scan.\n\nTable: {table_name}\nViolation: {detail}\nSeverity: {severity}"

    task_id = create_task_with_spirit(
        project_id=project_id,
        title=title,
        description=description,
        priority=2 if severity == "error" else 3,
        task_type="debt",
        tier=tier,
        objective=objective,
        spirit_anti="Do NOT break existing queries. Do NOT rename without updating all references.",
        done_when=done_when,
        complexity="SIMPLE",
        auto_approve=True,
    )

    if not task_id:
        return None, None

    link_task_to_issue(task_id, issue_id)
    create_single_subtask_with_steps(
        task_id=task_id,
        subtask_id="1.1",
        phase="backend",
        description=f"Fix {violation_type} in {table_name}",
        steps=steps,
    )

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
    """Create architecture task with spirit, subtasks, and steps."""
    issue_id = create_architecture_issue(project_id, violation_type, title, severity, len(violations), affected_files)
    description = build_architecture_description(violation_type, affected_files, len(violations))

    task_id = create_task_with_spirit(
        project_id=project_id,
        title=f"Architecture: {title}",
        description=description,
        priority=2 if severity == "error" else 3,
        task_type="refactor",
        tier=tier,
        objective=objective,
        spirit_anti="Do NOT break existing functionality. Fix violations systematically, not file-by-file randomly.",
        done_when=done_when,
        complexity=complexity,
        auto_approve=auto_approve,
    )

    if not task_id:
        return None, None

    link_task_to_issue(task_id, issue_id)
    create_architecture_subtasks(task_id, violation_type, affected_files)

    logger.info(f"Created consolidated architecture task {task_id} for {violation_type}: {len(affected_files)} files, linked to issue {issue_id}")
    return task_id, issue_id
