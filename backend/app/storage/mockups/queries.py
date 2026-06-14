"""Mockups queries - Read operations, filtering, and pagination."""

from __future__ import annotations

from typing import Any

from psycopg import sql

from .._sql import join_static_sql, static_sql
from ..connection import get_cursor
from .core import (
    MOCKUP_SELECT_COLUMNS,
    MOCKUP_SELECT_COLUMNS_ALIASED,
    MOCKUP_VOTE_SELECT_COLUMNS,
    _row_to_mockup,
)

_MOCKUP_VOTE_JOIN_SQL = """
LEFT JOIN (
    SELECT
        mockup_id,
        COUNT(*) FILTER (WHERE vote = 'up') AS thumbs_up,
        COUNT(*) FILTER (WHERE vote = 'down') AS thumbs_down
    FROM mockup_votes
    GROUP BY mockup_id
) vote_counts ON vote_counts.mockup_id = m.id
"""

_MOCKUP_SORT_SQL = {
    "created_desc": "m.created_at DESC",
    "thumbs_up": "thumbs_up DESC, m.created_at DESC",
    "thumbs_down": "thumbs_down DESC, m.created_at DESC",
    "vote_score": "vote_score DESC, thumbs_up DESC, m.created_at DESC",
}


def get_mockup(project_id: str, mockup_id: str) -> dict[str, Any] | None:
    """Get a mockup by project_id and mockup_id."""
    with get_cursor() as cur:
        cur.execute(
            static_sql(
                f"""
                SELECT {MOCKUP_SELECT_COLUMNS_ALIASED}, {MOCKUP_VOTE_SELECT_COLUMNS}
                FROM mockups m
                {_MOCKUP_VOTE_JOIN_SQL}
                WHERE m.project_id = %s AND m.mockup_id = %s
                """
            ),
            (project_id, mockup_id),
        )
        row = cur.fetchone()

        if not row:
            return None

        return _row_to_mockup(row)


def _build_filter_clauses(
    project_id: str,
    *,
    mockup_type: str | None = None,
    status: str | None = None,
    task_id: str | None = None,
    page_path: str | None = None,
    generator: str | None = None,
    search: str | None = None,
) -> tuple[list[str], list[Any]]:
    """Build WHERE clauses and params list from filter arguments."""
    where_clauses = ["m.project_id = %s"]
    params: list[Any] = [project_id]

    if mockup_type:
        where_clauses.append("m.mockup_type = %s")
        params.append(mockup_type)

    if status:
        where_clauses.append("m.status = %s")
        params.append(status)

    if task_id:
        where_clauses.append("m.task_id = %s")
        params.append(task_id)

    if page_path:
        where_clauses.append("m.page_path = %s")
        params.append(page_path)

    if generator:
        where_clauses.append("m.generator = %s")
        params.append(generator)

    if search:
        where_clauses.append("(m.name ILIKE %s OR m.description ILIKE %s)")
        search_pattern = f"%{search}%"
        params.extend([search_pattern, search_pattern])

    return where_clauses, params


def _count_mockups(cur: Any, where_sql: sql.Composed, params: list[Any]) -> int:
    """Execute a COUNT query and return the total."""
    cur.execute(
        sql.SQL("SELECT COUNT(*) FROM mockups m WHERE ") + where_sql,
        params,
    )
    count_row = cur.fetchone()
    return int(count_row[0]) if count_row and count_row[0] else 0


def list_mockups(
    project_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
    mockup_type: str | None = None,
    status: str | None = None,
    task_id: str | None = None,
    page_path: str | None = None,
    generator: str | None = None,
    search: str | None = None,
    sort_by: str = "created_desc",
) -> tuple[list[dict[str, Any]], int]:
    """List mockups for a project with filtering.

    Returns:
        Tuple of (mockups list, total count)
    """
    where_clauses, params = _build_filter_clauses(
        project_id,
        mockup_type=mockup_type,
        status=status,
        task_id=task_id,
        page_path=page_path,
        generator=generator,
        search=search,
    )
    order_by = _MOCKUP_SORT_SQL.get(sort_by)
    if order_by is None:
        raise ValueError(f"Invalid mockup sort: {sort_by}")
    where_sql = join_static_sql(where_clauses, " AND ")

    with get_cursor() as cur:
        total = _count_mockups(cur, where_sql, params.copy())

        cur.execute(
            static_sql(
                f"""
                SELECT {MOCKUP_SELECT_COLUMNS_ALIASED}, {MOCKUP_VOTE_SELECT_COLUMNS}
                FROM mockups m
                {_MOCKUP_VOTE_JOIN_SQL}
                WHERE
                """
            )
            + where_sql
            + static_sql(f" ORDER BY {order_by} LIMIT %s OFFSET %s"),
            [*params, limit, offset],
        )
        rows = cur.fetchall()

    return [_row_to_mockup(row) for row in rows], total


def get_mockups_for_task(
    project_id: str,
    task_id: str,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Get all mockups for a task."""
    with get_cursor() as cur:
        query = (
            f"SELECT {MOCKUP_SELECT_COLUMNS} FROM mockups WHERE project_id = %s AND task_id = %s"
        )
        params: list[Any] = [project_id, task_id]

        if status:
            query += " AND status = %s"
            params.append(status)

        query += " ORDER BY created_at DESC"

        cur.execute(static_sql(query), params)
        rows = cur.fetchall()

        return [_row_to_mockup(row) for row in rows]


def get_mockups_for_page(
    project_id: str,
    page_path: str,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Get all mockups for a specific page."""
    with get_cursor() as cur:
        query = (
            f"SELECT {MOCKUP_SELECT_COLUMNS} FROM mockups WHERE project_id = %s AND page_path = %s"
        )
        params: list[Any] = [project_id, page_path]

        if status:
            query += " AND status = %s"
            params.append(status)

        query += " ORDER BY version DESC, created_at DESC"

        cur.execute(static_sql(query), params)
        rows = cur.fetchall()

        return [_row_to_mockup(row) for row in rows]
