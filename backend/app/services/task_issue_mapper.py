"""Task-Issue Mapper Service for Self-Healing.

Maps QA issues to SummitFlow tasks and handles auto-close
when issues are resolved.

Implementation split across private submodules:
  _tim_constants.py   - shared constants, SQL, QAIssue dataclass
  _tim_st_commands.py - st CLI helpers and severity/domain mappings
  _tim_db_ops.py      - database read/write helpers
"""

from psycopg import Connection

from app.services._tim_constants import QAIssue  # re-exported for callers
from app.services._tim_db_ops import (
    db_get_issue_by_id,
    db_get_linked_task,
    db_link_issue_to_task,
)
from app.services._tim_st_commands import (
    _parse_task_id_from_output,
    build_create_task_args,
    run_st_command,
)

__all__ = [
    "QAIssue",
    "close_task_for_issue",
    "create_and_link_task_for_issue",
    "create_task_for_issue",
    "get_issue_by_id",
    "get_linked_task",
    "link_issue_to_task",
]

from ..logging_config import get_logger

logger = get_logger(__name__)


def create_task_for_issue(issue: QAIssue) -> str | None:
    """Create a SummitFlow task for a QA issue.

    Returns the task ID if created, None if failed.
    """
    args = build_create_task_args(
        project_id=issue.project_id,
        issue_id=issue.id,
        title=issue.title,
        severity=issue.severity,
        issue_type=issue.issue_type,
        description=issue.description,
        file_path=issue.file_path,
    )
    success, output = run_st_command(args)
    if not success:
        logger.error("Failed to create task for issue %d: %s", issue.id, output)
        return None

    task_id = _parse_task_id_from_output(output, issue.id)
    if not task_id:
        logger.error("Could not parse task ID from output: %s", output)
    return task_id


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


def get_linked_task(
    issue_id: int,
    conn: Connection | None = None,
) -> str | None:
    """Return the SummitFlow task ID linked to a QA issue, or None."""
    return db_get_linked_task(issue_id, conn)


def get_issue_by_id(
    issue_id: int,
    conn: Connection | None = None,
) -> QAIssue | None:
    """Fetch a QAIssue from the database by ID, or None."""
    return db_get_issue_by_id(issue_id, conn)


def create_and_link_task_for_issue(issue_id: int) -> str | None:
    """Create a task for an issue and link them.

    Convenience wrapper combining create_task_for_issue + link_issue_to_task.
    Returns the task ID if created and linked, None otherwise.
    """
    issue = get_issue_by_id(issue_id)
    if not issue:
        logger.error("Issue %d not found", issue_id)
        return None

    if issue.st_task_id:
        logger.debug("Issue %d already linked to task %s", issue_id, issue.st_task_id)
        return issue.st_task_id

    task_id = create_task_for_issue(issue)
    if not task_id:
        return None

    if link_issue_to_task(issue_id, task_id):
        return task_id
    return None
