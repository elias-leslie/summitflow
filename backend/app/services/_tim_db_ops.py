"""Database operations for task_issue_mapper."""

from __future__ import annotations

from psycopg import Connection

from app.services._tim_constants import (
    SQL_SELECT_ISSUE,
    SQL_SELECT_TASK_LINK,
    SQL_UPDATE_TASK_LINK,
    QAIssue,
)
from app.storage.connection import get_connection

from ..logging_config import get_logger

logger = get_logger(__name__)


def db_link_issue_to_task(
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


def db_get_linked_task(
    issue_id: int,
    conn: Connection | None = None,
) -> str | None:
    """Return the st_task_id for a qa_issue row."""

    def _do(c: Connection) -> str | None:
        with c.cursor() as cur:
            cur.execute(SQL_SELECT_TASK_LINK, (issue_id,))
            row = cur.fetchone()
            return row[0] if row else None

    if conn:
        return _do(conn)
    with get_connection() as c:
        return _do(c)


def db_get_issue_by_id(
    issue_id: int,
    conn: Connection | None = None,
) -> QAIssue | None:
    """Fetch a QAIssue from the database by primary key."""

    def _do(c: Connection) -> QAIssue | None:
        with c.cursor() as cur:
            cur.execute(SQL_SELECT_ISSUE, (issue_id,))
            row = cur.fetchone()
            if not row:
                return None
            return QAIssue(
                id=row[0],
                project_id=row[1],
                issue_type=row[2],
                severity=row[3],
                title=row[4],
                description=row[5],
                file_path=row[6],
                st_task_id=row[7],
            )

    if conn:
        return _do(conn)
    with get_connection() as c:
        return _do(c)
