"""Follow-up task creation for partial completions."""

from __future__ import annotations

from typing import Any

from ....logging_config import get_logger
from ....storage.tasks.core import create_task
from .events import emit_log

logger = get_logger(__name__)


def create_followup_task_for_failures(
    task_id: str,
    project_id: str,
    failed_results: list[dict[str, Any]],
) -> str | None:
    """Create a follow-up task for failed subtasks.

    Args:
        task_id: Parent task ID
        project_id: The project ID
        failed_results: List of failed subtask results

    Returns:
        Follow-up task ID if created, None otherwise
    """
    try:
        failed_desc = "\n".join(
            f"- {r.get('subtask_id', '?')}: {r.get('error', r.get('reason', 'failed'))[:100]}"
            for r in failed_results
        )

        follow_up = create_task(
            project_id=project_id,
            title=f"Follow-up: stuck subtasks from {task_id}",
            description=(
                f"Partial merge completed for task {task_id}. "
                f"The following subtasks could not be resolved:\n\n"
                f"{failed_desc}\n\n"
                f"These need to be re-attempted with a fresh approach."
            ),
            task_type="task",
            priority=1,
            parent_task_id=task_id,
            autonomous=True,
        )

        follow_up_id = str(follow_up.get("id", "unknown"))
        emit_log(
            task_id,
            "info",
            f"Created follow-up task {follow_up_id} for {len(failed_results)} stuck subtask(s)",
            project_id=project_id,
        )
        return follow_up_id

    except Exception as e:
        emit_log(
            task_id,
            "warn",
            f"Failed to create follow-up task: {e}",
            project_id=project_id,
        )
        return None
