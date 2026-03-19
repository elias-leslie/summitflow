"""Database operations for task_issue_mapper."""

from __future__ import annotations

from psycopg import Connection

from app.services._tim_constants import SQL_UPDATE_TASK_LINK
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
