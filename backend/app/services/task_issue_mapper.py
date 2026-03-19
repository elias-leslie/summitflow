"""Task-Issue Mapper Service for Self-Healing.

Maps QA issues to SummitFlow tasks and handles auto-close
when issues are resolved.

Implementation split across private submodules:
  _tim_constants.py   - shared constants, SQL, QAIssue dataclass
  _tim_st_commands.py - st CLI helpers
  _tim_db_ops.py      - database write helpers
"""

from psycopg import Connection

from app.services._tim_constants import QAIssue  # re-exported for callers
from app.services._tim_db_ops import db_link_issue_to_task
from app.services._tim_st_commands import run_st_command

__all__ = [
    "QAIssue",
    "close_task_for_issue",
    "link_issue_to_task",
]

from ..logging_config import get_logger

logger = get_logger(__name__)


def link_issue_to_task(
    issue_id: int,
    task_id: str,
    conn: Connection | None = None,
) -> bool:
    """Link a QA issue to a SummitFlow task (updates qa_issues.st_task_id)."""
    return db_link_issue_to_task(issue_id, task_id, conn)


def close_task_for_issue(issue: QAIssue) -> bool:
    """Cancel the SummitFlow task linked to a QA issue.

    Returns True if the task was cancelled successfully.
    """
    if not issue.st_task_id:
        logger.debug("Issue %d has no linked task to close", issue.id)
        return False

    reason = f"Auto-closed: QA issue #{issue.id} resolved"
    success, output = run_st_command(["cancel", issue.st_task_id, "--reason", reason])
    if success:
        logger.info("Auto-cancelled task %s for resolved issue %d", issue.st_task_id, issue.id)
        return True
    logger.warning("Failed to cancel task %s: %s", issue.st_task_id, output)
    return False


