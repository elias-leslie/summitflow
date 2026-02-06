"""Mockups queries - Read operations, filtering, and pagination."""

from __future__ import annotations

from typing import Any

from psycopg import sql

from ..connection import get_connection
from .core import MOCKUP_SELECT_COLUMNS, _row_to_mockup


def get_mockup(project_id: str, mockup_id: str) -> dict[str, Any] | None:
    """Get a mockup by project_id and mockup_id."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {MOCKUP_SELECT_COLUMNS} FROM mockups WHERE project_id = %s AND mockup_id = %s",
            (project_id, mockup_id),
        )
        row = cur.fetchone()

        if not row:
            return None

        return _row_to_mockup(row)


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
) -> tuple[list[dict[str, Any]], int]:
    """List mockups for a project with filtering.

    Returns:
        Tuple of (mockups list, total count)
    """
    with get_connection() as conn, conn.cursor() as cur:
        where_clauses = ["project_id = %s"]
        params: list[Any] = [project_id]

        if mockup_type:
            where_clauses.append("mockup_type = %s")
            params.append(mockup_type)

        if status:
            where_clauses.append("status = %s")
            params.append(status)

        if task_id:
            where_clauses.append("task_id = %s")
            params.append(task_id)

        if page_path:
            where_clauses.append("page_path = %s")
            params.append(page_path)

        if generator:
            where_clauses.append("generator = %s")
            params.append(generator)

        if search:
            where_clauses.append("(name ILIKE %s OR description ILIKE %s)")
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern])

        where_sql = sql.SQL(" AND ").join(sql.SQL(c) for c in where_clauses)

        # Get total count
        count_params = params.copy()
        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM mockups WHERE ") + where_sql,
            count_params,
        )
        count_row = cur.fetchone()
        total = int(count_row[0]) if count_row and count_row[0] else 0

        # Get paginated results
        params.extend([limit, offset])
        cur.execute(
            sql.SQL(f"SELECT {MOCKUP_SELECT_COLUMNS} FROM mockups WHERE ")
            + where_sql
            + sql.SQL(" ORDER BY created_at DESC LIMIT %s OFFSET %s"),
            params,
        )
        rows = cur.fetchall()

        return [_row_to_mockup(row) for row in rows], total


def get_mockups_for_task(
    project_id: str,
    task_id: str,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Get all mockups for a task."""
    with get_connection() as conn, conn.cursor() as cur:
        query = (
            f"SELECT {MOCKUP_SELECT_COLUMNS} FROM mockups WHERE project_id = %s AND task_id = %s"
        )
        params: list[Any] = [project_id, task_id]

        if status:
            query += " AND status = %s"
            params.append(status)

        query += " ORDER BY created_at DESC"

        cur.execute(query, params)
        rows = cur.fetchall()

        return [_row_to_mockup(row) for row in rows]


def get_mockups_for_page(
    project_id: str,
    page_path: str,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Get all mockups for a specific page."""
    with get_connection() as conn, conn.cursor() as cur:
        query = (
            f"SELECT {MOCKUP_SELECT_COLUMNS} FROM mockups WHERE project_id = %s AND page_path = %s"
        )
        params: list[Any] = [project_id, page_path]

        if status:
            query += " AND status = %s"
            params.append(status)

        query += " ORDER BY version DESC, created_at DESC"

        cur.execute(query, params)
        rows = cur.fetchall()

        return [_row_to_mockup(row) for row in rows]
