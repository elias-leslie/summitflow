"""Autocode validation logic.

Handles task validation and quality gate checks before execution.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ...logging_config import get_logger
from ...storage import quality_check_results as qcr_store
from ...storage.connection import get_connection
from ...storage.subtasks import get_subtasks_for_task

logger = get_logger(__name__)


def validate_task_exists(
    task: dict[str, Any] | None,
    task_id: str,
) -> None:
    """Validate task exists.

    Args:
        task: Task dict or None
        task_id: Task ID being validated

    Raises:
        HTTPException(404): If task not found
    """
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")


def validate_task_in_project(
    task: dict[str, Any],
    task_id: str,
    project_id: str,
) -> None:
    """Validate task belongs to project.

    Args:
        task: Task dict
        task_id: Task ID
        project_id: Expected project ID

    Raises:
        HTTPException(404): If task not in project
    """
    if task["project_id"] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found in project {project_id}",
        )


def validate_has_subtasks(task_id: str) -> list[dict[str, Any]]:
    """Validate task has subtasks.

    Args:
        task_id: Task ID

    Returns:
        List of subtasks

    Raises:
        HTTPException(400): If no subtasks found
    """
    subtasks = get_subtasks_for_task(task_id)
    if not subtasks:
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} has no subtasks. Cannot run autocode without subtasks.",
        )
    return subtasks


def validate_has_done_when(
    task: dict[str, Any],
    task_id: str,
) -> None:
    """Validate task has done_when criteria.

    Args:
        task: Task dict
        task_id: Task ID

    Raises:
        HTTPException(400): If no done_when criteria
    """
    done_when = task.get("done_when")
    if not done_when:
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} has no done_when criteria. Cannot run autocode without acceptance criteria.",
        )


def check_and_fix_quality_gates(project_id: str) -> None:
    """Check quality gates and auto-fix if failing.

    Args:
        project_id: Project ID

    Raises:
        HTTPException(400): If quality gates still failing after auto-fix
    """
    with get_connection() as conn:
        health = qcr_store.get_project_health_summary(conn, project_id)
        if not health["overall_pass"] and health["total_unfixed"] > 0:
            # Auto-trigger fix agent
            from app.services.quality_gate import fix_unfixed_errors
            from app.services.quality_gate.test_fix_agent import fix_failing_tests

            logger.info(
                "quality_gate_auto_fix_triggered",
                project_id=project_id,
                unfixed_count=health["total_unfixed"],
            )

            # Try to fix lint/type errors first
            lint_results = fix_unfixed_errors(conn, project_id, limit=20)
            # Then test failures
            test_results = fix_failing_tests(conn, project_id, limit=5)
            conn.commit()

            total_fixed = lint_results["fixed"] + test_results["fixed"]
            total_escalated = lint_results["escalated"] + test_results["escalated"]

            # Re-check health after fix attempt
            health = qcr_store.get_project_health_summary(conn, project_id)

            if not health["overall_pass"] and health["total_unfixed"] > 0:
                failing_checks = [
                    f"{ct}: {info['unfixed_count']} unfixed"
                    for ct, info in health["checks"].items()
                    if info.get("unfixed_count", 0) > 0
                ]
                detail = (
                    f"Quality gate failing after auto-fix "
                    f"(fixed {total_fixed}, escalated {total_escalated}). "
                    f"Remaining: {', '.join(failing_checks)}"
                )
                raise HTTPException(status_code=400, detail=detail)

            logger.info(
                "quality_gate_auto_fix_success",
                project_id=project_id,
                fixed=total_fixed,
            )
