"""Task validation service - Pre-work validation for tasks.

This module provides validation logic to check if a task is ready to be worked on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..storage import task_dependencies as dep_store
from ..storage import tasks as task_store
from ..storage.connection import get_connection


@dataclass
class ValidationResult:
    """Result of task validation."""

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


# Common verbs that indicate actionable criteria
ACTION_VERBS = {
    "add", "create", "build", "implement", "write", "develop",
    "fix", "update", "modify", "change", "remove", "delete",
    "display", "show", "render", "fetch", "load", "save",
    "validate", "verify", "check", "test", "ensure",
    "enable", "disable", "toggle", "configure", "set",
    "send", "receive", "process", "handle", "parse",
    "connect", "disconnect", "open", "close",
    "return", "accept", "reject", "allow", "deny",
    "click", "submit", "navigate", "redirect",
    "authenticate", "authorize", "log", "track",
}


def _has_action_verb(text: str) -> bool:
    """Check if text contains an action verb.

    Args:
        text: Text to check

    Returns:
        True if text contains an action verb
    """
    words = set(re.findall(r"\b\w+\b", text.lower()))
    return bool(words & ACTION_VERBS)


def _get_word_count(text: str) -> int:
    """Count words in text.

    Args:
        text: Text to count words in

    Returns:
        Number of words
    """
    return len(re.findall(r"\b\w+\b", text))


def _get_feature_for_task(feature_db_id: int) -> dict[str, Any] | None:
    """Get feature by database ID.

    Args:
        feature_db_id: Feature database ID (not the string feature_id)

    Returns:
        Feature dict with acceptance_criteria or None
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, feature_id, name, acceptance_criteria
            FROM feature_capabilities
            WHERE id = %s
            """,
            (feature_db_id,),
        )
        row = cur.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "feature_id": row[1],
        "name": row[2],
        "acceptance_criteria": row[3] or [],
    }


def validate_task_ready(task_id: str, project_id: str) -> ValidationResult:
    """Validate if a task is ready to be worked on.

    Performs the following checks:
    1. Task exists and belongs to project
    2. Task is not already running or completed
    3. Task has no incomplete blocking dependencies
    4. For feature-type tasks:
       - Must be linked to a feature with ≥1 acceptance criterion
       - Criteria should be specific (>10 words, has action verb)

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

    # Check feature-type tasks
    task_type = task.get("task_type", "task")
    if task_type == "feature":
        feature_db_id = task.get("feature_id")

        if not feature_db_id:
            issues.append("Feature-type task is not linked to a feature")
            suggestions.append("Link this task to a feature with acceptance criteria")
        else:
            # Get the linked feature
            feature = _get_feature_for_task(feature_db_id)
            if not feature:
                issues.append(f"Linked feature (ID: {feature_db_id}) not found")
            else:
                criteria = feature.get("acceptance_criteria", [])
                if not criteria:
                    issues.append(
                        f"Feature '{feature['feature_id']}' has no acceptance criteria"
                    )
                    suggestions.append(
                        "Add specific acceptance criteria to the feature before starting work"
                    )
                else:
                    # Check criteria quality
                    weak_criteria = []
                    for criterion in criteria:
                        desc = criterion.get("description", "")
                        crit_id = criterion.get("id", "?")

                        word_count = _get_word_count(desc)
                        has_verb = _has_action_verb(desc)

                        if word_count < 10:
                            weak_criteria.append(
                                f"{crit_id}: Too short ({word_count} words, need 10+)"
                            )
                        elif not has_verb:
                            weak_criteria.append(
                                f"{crit_id}: Missing action verb (add, create, show, etc.)"
                            )

                    if weak_criteria:
                        # Only warn, don't block
                        suggestions.append(
                            f"Consider improving these criteria: {'; '.join(weak_criteria)}"
                        )

    # Determine if ready
    ready = len(issues) == 0

    return ValidationResult(
        ready=ready,
        issues=issues,
        suggestions=suggestions,
    )
