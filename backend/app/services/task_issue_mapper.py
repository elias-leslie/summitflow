"""Task-Issue Mapper Service for Self-Healing.

Maps QA issues to SummitFlow tasks and handles auto-close
when issues are resolved.
"""

from __future__ import annotations

from dataclasses import dataclass

from psycopg import Connection

from ..logging_config import get_logger
from ..storage import tasks as task_store
from ..storage.connection import get_connection
from ..storage.events import log_task_event

logger = get_logger(__name__)

__all__ = [
    "QAIssue",
    "close_task_for_issue",
    "link_issue_to_task",
]

SQL_UPDATE_TASK_LINK = """
    UPDATE qa_issues
    SET st_task_id = %s, updated_at = NOW()
    WHERE id = %s
"""


@dataclass
class QAIssue:
    """Minimal issue data needed for task mapping."""

    id: int
    project_id: str
    issue_type: str
    severity: str
    title: str
    description: str | None
    file_path: str | None
    st_task_id: str | None


def _db_link_issue_to_task(
    issue_id: int,
    task_id: str,
    conn: Connection | None = None,
) -> bool:
    """Update qa_issues to set st_task_id for the given issue."""

    def _do(c: Connection) -> bool:
        with c.cursor() as cur:
            cur.execute(SQL_UPDATE_TASK_LINK, (task_id, issue_id))
            if cur.rowcount > 0:
                logger.info("Linked issue %d to task %s", issue_id, task_id)
                return True
            logger.warning("Issue %d not found for linking", issue_id)
            return False

    if conn:
        return _do(conn)
    with get_connection() as c:
        result = _do(c)
        c.commit()
        return result


# ── Public API ─────────────────────────────────────────────────────────


def link_issue_to_task(
    issue_id: int,
    task_id: str,
    conn: Connection | None = None,
) -> bool:
    """Link a QA issue to a SummitFlow task (updates qa_issues.st_task_id)."""
    return _db_link_issue_to_task(issue_id, task_id, conn)


def close_task_for_issue(issue: QAIssue) -> bool:
    """Cancel the SummitFlow task linked to a QA issue.

    Returns True if the task was cancelled successfully.
    """
    if not issue.st_task_id:
        logger.debug("Issue %d has no linked task to close", issue.id)
        return False

    reason = f"Auto-closed: QA issue #{issue.id} resolved"
    task = task_store.get_task(issue.st_task_id)
    if not task:
        logger.warning("Task %s linked to issue %d no longer exists", issue.st_task_id, issue.id)
        return False

    current_status = task.get("status")
    if current_status in {"completed", "cancelled"}:
        logger.info(
            "Skipping auto-cancel for task %s in terminal status %s",
            issue.st_task_id,
            current_status,
        )
        return False

    try:
        task_store.update_task_status(issue.st_task_id, "cancelled")
        log_task_event(issue.st_task_id, reason, source="explorer_resolution")
        return True
    except Exception:
        logger.exception("Failed to cancel task %s for resolved issue %d", issue.st_task_id, issue.id)
        return False
