"""Core task creation utilities."""

from __future__ import annotations

import logging
from typing import cast

from app.services.task_issue_mapper import link_issue_to_task
from app.storage import tasks as task_store
from app.storage.task_spirit import approve_plan, create_task_spirit

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

_SIZE_ISSUES = frozenset({"oversized", "large_file", "bloat_critical", "bloat_warning"})

_STRUCTURAL_CRITERIA: dict[str, str] = {
    "has_long_functions": "No functions exceed 50 lines",
    "deep_nesting": "No nesting deeper than 3 levels",
    "too_many_functions": "Functions per file reduced to <=20",
    "too_many_classes": "Classes per file reduced to <=5",
    "has_large_classes": "No class has more than 10 methods",
    "magic_strings": "Magic strings extracted to constants or config",
    "too_many_imports": "Imports reduced to <=30",
}


def _build_issue_aware_objective(
    relative_path: str,
    lines: int,
    target_lines: int,
    refactor_issues: list[str],
) -> str:
    """Build task objective from actual issues, not just line count."""
    parts = [f"Refactor {relative_path}"]

    if any(i in _SIZE_ISSUES for i in refactor_issues):
        parts.append(f"to simplify and reduce size from {lines} lines (aim for <{target_lines} where it helps)")

    structural_issues = [i for i in refactor_issues if i not in _SIZE_ISSUES | {"high_complexity", "medium_complexity"}]
    if structural_issues:
        issue_labels = [_ISSUE_LABELS.get(i, i.replace("_", " ")) for i in structural_issues[:4]]
        parts.append(f"resolving: {', '.join(issue_labels)}")

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

    if any(i in _SIZE_ISSUES for i in refactor_issues):
        criteria.append(
            f"File structure is meaningfully simplified, with size reduced toward the guideline target of <{target_lines} lines from {lines} where appropriate"
        )

    criteria.extend(
        criterion
        for issue_key, criterion in _STRUCTURAL_CRITERIA.items()
        if issue_key in refactor_issues
    )

    criteria.append("No regressions - all existing tests pass")
    if is_frontend:
        criteria.append("No console errors in browser")

    return criteria


def _create_base_task(
    project_id: str,
    title: str,
    description: str,
    priority: int,
    task_type: str,
    tier: int,
    ai_review: bool,
) -> str | None:
    """Create the base task record and return its ID, or None on failure."""
    task = task_store.create_task(
        project_id=project_id,
        title=title,
        description=description,
        priority=priority,
        task_type=task_type,
        tier=tier,
        ai_review=ai_review,
    )
    if not task:
        return None
    return cast(str, task["id"])


def _attach_spirit_and_approve(
    task_id: str,
    objective: str,
    spirit_anti: str,
    done_when: list[str],
    complexity: str,
    context: dict[str, object] | None,
    auto_approve: bool,
) -> None:
    """Attach a spirit to the task and optionally auto-approve the plan."""
    create_task_spirit(
        task_id=task_id,
        objective=objective,
        spirit_anti=spirit_anti,
        done_when=done_when,
        context=context,
        complexity=complexity,
    )
    if auto_approve:
        approve_plan(task_id, approved_by="auto-generated")


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
    context: dict[str, object] | None = None,
    auto_approve: bool = True,
    ai_review: bool = True,
) -> str | None:
    """Create a task with an attached spirit.

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
        ai_review: Whether to run AI review before completion

    Returns:
        Task ID or None if creation failed
    """
    task_id = _create_base_task(project_id, title, description, priority, task_type, tier, ai_review)
    if not task_id:
        return None
    _attach_spirit_and_approve(
        task_id,
        objective,
        spirit_anti,
        done_when,
        complexity,
        context,
        auto_approve,
    )
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
    promotion_reasons: list[str] | None = None,
    promotion_confidence: str | None = None,
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
    description = (
        f"Auto-generated from Explorer scan.\n\n"
        f"File: {relative_path}\n"
        f"Lines: {lines} (guideline: aim for <{target_lines} if the refactor stays clean)\n"
        f"Complexity: {complexity:.1f}\n"
        f"Priority: {priority}"
    )
    reasons = [str(reason) for reason in (promotion_reasons or []) if reason]
    if reasons:
        description += (
            "\n"
            f"Promotion confidence: {promotion_confidence or 'medium'}\n"
            "Promotion evidence:\n- "
            + "\n- ".join(reasons[:4])
        )
    return description


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
    for affected_file in affected_files[:15]:
        description += f"- {affected_file}\n"
    if len(affected_files) > 15:
        description += f"- ... and {len(affected_files) - 15} more files\n"
    return description
