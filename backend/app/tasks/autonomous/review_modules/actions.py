"""Review actions: auto-merge, create fix subtasks, handle defects."""

from __future__ import annotations

from typing import Any

from ....logging_config import get_logger
from ....storage import tasks as task_store

logger = get_logger(__name__)


def auto_merge(task_id: str) -> None:
    """Auto-merge changes to main branch.

    Triggers the merge_and_cleanup_task_worktree workflow to:
    1. Merge task branch to main
    2. Remove the worktree
    3. Delete the task branch

    Args:
        task_id: Task ID to merge
    """
    from ..cleanup import merge_and_cleanup_task_worktree

    task = task_store.get_task(task_id)
    if not task:
        logger.warning("Cannot auto-merge: task not found", task_id=task_id)
        return

    project_id = task.get("project_id")
    if not project_id:
        logger.warning("Cannot auto-merge: no project_id", task_id=task_id)
        return

    logger.info("Triggering auto-merge", task_id=task_id, project_id=project_id)
    merge_and_cleanup_task_worktree(task_id, project_id)


def create_fix_subtask(task_id: str, review_result: dict[str, Any]) -> None:
    """Create fix subtask from reviewer feedback.

    Args:
        task_id: Task ID to add fix subtask to
        review_result: Review result with concerns and recommendations
    """
    from ....storage.subtasks import create_subtask

    concerns = review_result.get("concerns", [])
    recommendation = review_result.get(
        "recommendation", "Address reviewer concerns"
    )

    description = (
        f"Fix: {recommendation}\n\nReviewer concerns:\n"
        + "\n".join(f"- {c}" for c in concerns)
    )

    create_subtask(
        task_id=task_id,
        subtask_id="99.1",
        description=description[:500],
        display_order=99,
        phase="backend",
        steps=[
            {"description": "Address reviewer feedback", "verify_command": None}
        ],
    )

    logger.info("Created fix subtask from review feedback", task_id=task_id)


def handle_plan_defect(task_id: str, review_result: dict[str, Any]) -> None:
    """Handle plan defect by adding fix step with correct verification.

    When the implementation is correct but the verify_command is wrong,
    we add a fix step that proves correctness and mark the original as defect.

    Args:
        task_id: Task ID to add plan defect fix to
        review_result: Review result with fix steps and recommendations
    """
    from ....storage.subtasks import create_subtask

    recommendation = review_result.get(
        "recommendation", "Implementation correct, verification fixed"
    )
    fix_steps = review_result.get("fix_steps", [])

    steps_list: list[str | dict[str, Any]] = []
    for fix in fix_steps:
        steps_list.append(
            {
                "description": fix if isinstance(fix, str) else str(fix),
                "verify_command": None,
            }
        )

    if not steps_list:
        steps_list = [
            {
                "description": "Verify correct implementation with fixed command",
                "verify_command": None,
            }
        ]

    create_subtask(
        task_id=task_id,
        subtask_id="98.1",
        description=f"Plan Defect Fix: {recommendation[:400]}",
        display_order=98,
        phase="verification",
        steps=steps_list,
    )

    logger.info("Created plan defect fix subtask", task_id=task_id)
