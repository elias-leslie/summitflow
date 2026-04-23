"""Follow-up task creation for partial completions."""

from __future__ import annotations

from typing import Any

from ....logging_config import get_logger
from ....storage.connection import get_connection
from ....storage.tasks.columns import TASK_COLUMNS
from ....storage.tasks.core import canonicalize_task_id, create_task
from ....storage.tasks.mapping import row_to_dict
from ....storage.tasks.update import update_task_fields
from .events import emit_log

logger = get_logger(__name__)

_PENDING_STATUS = "pending"


def _normalize_failed_subtask_ids(failed_results: list[dict[str, Any]]) -> list[str]:
    """Return sorted unique usable subtask ids from failed results."""
    normalized: set[str] = set()
    for result in failed_results:
        raw_subtask_id = result.get("subtask_id")
        if not isinstance(raw_subtask_id, str):
            continue
        subtask_id = raw_subtask_id.strip()
        if not subtask_id:
            continue
        normalized.add(subtask_id)
    return sorted(normalized)


def _build_followup_title(task_id: str) -> str:
    """Return exact follow-up title for parent task."""
    return f"Follow-up: stuck subtasks from {task_id}"


def _build_followup_description(task_id: str, failed_results: list[dict[str, Any]]) -> str:
    """Return normalized follow-up description text."""
    subtask_ids = _normalize_failed_subtask_ids(failed_results)
    failed_desc = "\n".join(f"- {subtask_id}" for subtask_id in subtask_ids)
    if not failed_desc:
        failed_desc = "- __no_subtask_ids__"
    return (
        f"Partial merge completed for task {task_id}. "
        f"The following subtasks could not be resolved:\n\n"
        f"{failed_desc}\n\n"
        f"These need to be re-attempted with a fresh approach."
    )


def _find_pending_followup_task(
    parent_task_id: str,
    project_id: str,
    title: str,
) -> dict[str, Any] | None:
    """Return oldest pending direct child follow-up task."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {TASK_COLUMNS}
            FROM tasks
            WHERE project_id = %s
              AND parent_task_id = %s
              AND title = %s
              AND status = %s
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """,
            (project_id, parent_task_id, title, _PENDING_STATUS),
        )
        row = cur.fetchone()
    return row_to_dict(row) if row else None


def _reuse_followup(
    parent_task_id: str,
    project_id: str,
    followup_task: dict[str, Any],
    description: str,
) -> str:
    update_task_fields(followup_task["id"], description=description)
    emit_log(
        parent_task_id,
        "info",
        f"Reused follow-up task {followup_task['id']} for failed subtasks",
        project_id=project_id,
    )
    return str(followup_task["id"])


def create_followup_task_for_failures(
    task_id: str | None,
    project_id: str,
    failed_results: list[dict[str, Any]],
) -> str | None:
    """Create or reuse a follow-up task for failed subtasks."""
    if not isinstance(task_id, str) or not task_id.strip():
        emit_log(
            task_id if isinstance(task_id, str) else "",
            "warn",
            "Skipped follow-up task creation: invalid parent task id",
            project_id=project_id,
        )
        return None

    try:
        parent_task_id = canonicalize_task_id(task_id)
        title = _build_followup_title(parent_task_id)
        description = _build_followup_description(parent_task_id, failed_results)
        existing_followup = _find_pending_followup_task(parent_task_id, project_id, title)
        if existing_followup is not None:
            return _reuse_followup(parent_task_id, project_id, existing_followup, description)

        created_followup = create_task(
            project_id=project_id,
            title=title,
            description=description,
            task_type="task",
            priority=1,
            parent_task_id=parent_task_id,
            autonomous=True,
        )
        authoritative_followup = _find_pending_followup_task(parent_task_id, project_id, title)
        if authoritative_followup is not None:
            if authoritative_followup["id"] == created_followup["id"]:
                emit_log(
                    parent_task_id,
                    "info",
                    f"Created follow-up task {created_followup['id']} for failed subtasks",
                    project_id=project_id,
                )
                return str(created_followup["id"])
            return _reuse_followup(parent_task_id, project_id, authoritative_followup, description)

        follow_up_id = str(created_followup.get("id", "unknown"))
        emit_log(
            parent_task_id,
            "info",
            f"Created follow-up task {follow_up_id} for failed subtasks",
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
