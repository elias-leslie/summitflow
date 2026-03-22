"""Task-Issue Mapper Service for Self-Healing.

Maps QA issues to SummitFlow tasks and handles auto-close
when issues are resolved.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from psycopg import Connection

from ..logging_config import get_logger
from ..storage.connection import get_connection

logger = get_logger(__name__)

__all__ = [
    "QAIssue",
    "close_task_for_issue",
    "link_issue_to_task",
]

# ── Constants ──────────────────────────────────────────────────────────

ST_COMMAND_TIMEOUT = 30

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


# ── Helpers ────────────────────────────────────────────────────────────


def _run_st_command(args: list[str]) -> tuple[bool, str]:
    """Run an st CLI command and return (success, output)."""
    try:
        result = subprocess.run(
            ["st", *args],
            capture_output=True,
            text=True,
            timeout=ST_COMMAND_TIMEOUT,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        logger.warning("st command failed: %s", result.stderr)
        return False, result.stderr.strip()
    except subprocess.TimeoutExpired:
        logger.error("st command timed out")
        return False, "Command timed out"
    except FileNotFoundError:
        logger.error("st CLI not found in PATH")
        return False, "st CLI not found"


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
    success, output = _run_st_command(["cancel", issue.st_task_id, "--reason", reason])
    if success:
        logger.info("Auto-cancelled task %s for resolved issue %d", issue.st_task_id, issue.id)
        return True
    logger.warning("Failed to cancel task %s: %s", issue.st_task_id, output)
    return False
