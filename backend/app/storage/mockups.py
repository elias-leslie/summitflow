"""Mockups Storage - Database operations for design mockups.

This module handles all database interactions for mockup records:
- CRUD operations for mockups
- Query filtering and pagination
- Approval workflow
- Provenance tracking
"""

from __future__ import annotations

import uuid
from typing import Any

from psycopg import sql

from .connection import get_connection

# Mockup type constants
MOCKUP_TYPES = frozenset({"component", "page", "layout", "icon", "illustration"})

# Mockup status constants
MOCKUP_STATUSES = frozenset(
    {"generated", "pending_approval", "approved", "rejected", "applied", "archived"}
)


def generate_mockup_id() -> str:
    """Generate a new mockup ID in the format mk-{uuid}."""
    return f"mk-{uuid.uuid4().hex[:12]}"


# Base SELECT columns for mockup queries
MOCKUP_SELECT_COLUMNS = """id, project_id, mockup_id, name, description, mockup_type,
       file_path, content, status, approved_at, approved_by, applied_at,
       task_id, page_path, version, parent_mockup_id, generator,
       generation_prompt, generation_time_ms, iteration_count, created_at, updated_at"""


def _row_to_mockup(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert database row to mockup dict."""
    return {
        "id": row[0],
        "project_id": row[1],
        "mockup_id": row[2],
        "name": row[3],
        "description": row[4],
        "mockup_type": row[5],
        "file_path": row[6],
        "content": row[7],
        "status": row[8],
        "approved_at": row[9].isoformat() if row[9] else None,
        "approved_by": row[10],
        "applied_at": row[11].isoformat() if row[11] else None,
        "task_id": row[12],
        "page_path": row[13],
        "version": row[14],
        "parent_mockup_id": row[15],
        "generator": row[16],
        "generation_prompt": row[17],
        "generation_time_ms": row[18],
        "iteration_count": row[19],
        "created_at": row[20].isoformat() if row[20] else None,
        "updated_at": row[21].isoformat() if row[21] else None,
    }


# ============================================================
# Create functions
# ============================================================


def create_mockup(
    project_id: str,
    name: str,
    *,
    description: str | None = None,
    mockup_type: str = "component",
    file_path: str | None = None,
    content: str | None = None,
    task_id: str | None = None,
    page_path: str | None = None,
    parent_mockup_id: int | None = None,
    generator: str | None = None,
    generation_prompt: str | None = None,
    generation_time_ms: int | None = None,
) -> dict[str, Any]:
    """Create a new mockup record.

    Args:
        project_id: Project ID
        name: Mockup name
        description: Mockup description (optional)
        mockup_type: Type of mockup (component, page, layout, icon, illustration)
        file_path: Path to mockup file (optional)
        content: Mockup content (optional, e.g., base64 image or HTML)
        task_id: Task ID if mockup is associated with a task
        page_path: Page path if mockup is for a specific page
        parent_mockup_id: Parent mockup ID for iterations
        generator: Name of the generator (e.g., "frontend-design", "gemini-2.0")
        generation_prompt: Prompt used to generate the mockup
        generation_time_ms: Time taken to generate the mockup

    Returns:
        Created mockup record
    """
    if mockup_type not in MOCKUP_TYPES:
        raise ValueError(f"Invalid mockup_type: {mockup_type}. Must be one of {MOCKUP_TYPES}")

    mockup_id = generate_mockup_id()

    # Determine version based on parent
    version = 1
    if parent_mockup_id:
        parent = get_mockup_by_db_id(parent_mockup_id)
        if parent:
            version = parent["version"] + 1

    # Determine iteration count
    iteration_count = 1
    if parent_mockup_id:
        parent = get_mockup_by_db_id(parent_mockup_id)
        if parent:
            iteration_count = parent["iteration_count"] + 1

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO mockups (
                project_id, mockup_id, name, description, mockup_type,
                file_path, content, status, task_id, page_path,
                version, parent_mockup_id, generator, generation_prompt,
                generation_time_ms, iteration_count
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'generated', %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {MOCKUP_SELECT_COLUMNS}
            """,
            (
                project_id,
                mockup_id,
                name,
                description,
                mockup_type,
                file_path,
                content,
                task_id,
                page_path,
                version,
                parent_mockup_id,
                generator,
                generation_prompt,
                generation_time_ms,
                iteration_count,
            ),
        )
        row = cur.fetchone()
        conn.commit()

        if not row:
            raise RuntimeError("Failed to create mockup record")

        return _row_to_mockup(row)


# ============================================================
# Read functions
# ============================================================


def get_mockup(project_id: str, mockup_id: str) -> dict[str, Any] | None:
    """Get a mockup by project_id and mockup_id."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {MOCKUP_SELECT_COLUMNS} FROM mockups "
            "WHERE project_id = %s AND mockup_id = %s",
            (project_id, mockup_id),
        )
        row = cur.fetchone()

        if not row:
            return None

        return _row_to_mockup(row)


def get_mockup_by_db_id(db_id: int) -> dict[str, Any] | None:
    """Get a mockup by database ID (primary key)."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {MOCKUP_SELECT_COLUMNS} FROM mockups WHERE id = %s",
            (db_id,),
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
            f"SELECT {MOCKUP_SELECT_COLUMNS} FROM mockups "
            "WHERE project_id = %s AND task_id = %s"
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
            f"SELECT {MOCKUP_SELECT_COLUMNS} FROM mockups "
            "WHERE project_id = %s AND page_path = %s"
        )
        params: list[Any] = [project_id, page_path]

        if status:
            query += " AND status = %s"
            params.append(status)

        query += " ORDER BY version DESC, created_at DESC"

        cur.execute(query, params)
        rows = cur.fetchall()

        return [_row_to_mockup(row) for row in rows]


def get_mockup_history(project_id: str, mockup_id: str) -> list[dict[str, Any]]:
    """Get the iteration history of a mockup (including parent chain)."""
    mockup = get_mockup(project_id, mockup_id)
    if not mockup:
        return []

    history = [mockup]

    # Walk up the parent chain
    current = mockup
    while current.get("parent_mockup_id"):
        parent = get_mockup_by_db_id(current["parent_mockup_id"])
        if not parent:
            break
        history.append(parent)
        current = parent

    # Return oldest first
    return list(reversed(history))


# ============================================================
# Update functions
# ============================================================


def update_mockup(
    project_id: str,
    mockup_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    file_path: str | None = None,
    content: str | None = None,
    page_path: str | None = None,
) -> dict[str, Any] | None:
    """Update mockup fields.

    Only allows updating non-provenance fields.
    """
    updates = []
    params: list[Any] = []

    if name is not None:
        updates.append("name = %s")
        params.append(name)

    if description is not None:
        updates.append("description = %s")
        params.append(description)

    if file_path is not None:
        updates.append("file_path = %s")
        params.append(file_path)

    if content is not None:
        updates.append("content = %s")
        params.append(content)

    if page_path is not None:
        updates.append("page_path = %s")
        params.append(page_path)

    if not updates:
        return get_mockup(project_id, mockup_id)

    params.extend([project_id, mockup_id])

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE mockups
            SET {", ".join(updates)}
            WHERE project_id = %s AND mockup_id = %s
            RETURNING {MOCKUP_SELECT_COLUMNS}
            """,
            params,
        )
        row = cur.fetchone()
        conn.commit()

        if not row:
            return None

        return _row_to_mockup(row)


def update_mockup_status(
    project_id: str,
    mockup_id: str,
    status: str,
    *,
    approved_by: str | None = None,
) -> dict[str, Any] | None:
    """Update mockup status.

    Args:
        project_id: Project ID
        mockup_id: Mockup ID
        status: New status
        approved_by: Who approved (required if status is 'approved')
    """
    if status not in MOCKUP_STATUSES:
        raise ValueError(f"Invalid status: {status}. Must be one of {MOCKUP_STATUSES}")

    with get_connection() as conn, conn.cursor() as cur:
        if status == "approved":
            cur.execute(
                f"""
                UPDATE mockups
                SET status = %s, approved_at = NOW(), approved_by = %s
                WHERE project_id = %s AND mockup_id = %s
                RETURNING {MOCKUP_SELECT_COLUMNS}
                """,
                (status, approved_by, project_id, mockup_id),
            )
        elif status == "applied":
            cur.execute(
                f"""
                UPDATE mockups
                SET status = %s, applied_at = NOW()
                WHERE project_id = %s AND mockup_id = %s
                RETURNING {MOCKUP_SELECT_COLUMNS}
                """,
                (status, project_id, mockup_id),
            )
        else:
            cur.execute(
                f"""
                UPDATE mockups
                SET status = %s
                WHERE project_id = %s AND mockup_id = %s
                RETURNING {MOCKUP_SELECT_COLUMNS}
                """,
                (status, project_id, mockup_id),
            )
        row = cur.fetchone()
        conn.commit()

        if not row:
            return None

        return _row_to_mockup(row)


# ============================================================
# Delete functions
# ============================================================


def delete_mockup(project_id: str, mockup_id: str) -> bool:
    """Delete a mockup by project_id and mockup_id.

    Returns:
        True if deleted, False if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM mockups WHERE project_id = %s AND mockup_id = %s RETURNING id",
            (project_id, mockup_id),
        )
        row = cur.fetchone()
        conn.commit()

        return row is not None


def archive_mockup(project_id: str, mockup_id: str) -> dict[str, Any] | None:
    """Archive a mockup (soft delete by setting status to 'archived')."""
    return update_mockup_status(project_id, mockup_id, "archived")


# ============================================================
# Aggregation functions
# ============================================================


def get_mockup_stats(project_id: str) -> dict[str, Any]:
    """Get mockup statistics for a project."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'generated') as generated,
                COUNT(*) FILTER (WHERE status = 'pending_approval') as pending_approval,
                COUNT(*) FILTER (WHERE status = 'approved') as approved,
                COUNT(*) FILTER (WHERE status = 'rejected') as rejected,
                COUNT(*) FILTER (WHERE status = 'applied') as applied,
                COUNT(*) FILTER (WHERE status = 'archived') as archived,
                COUNT(DISTINCT generator) as unique_generators,
                AVG(generation_time_ms) FILTER (WHERE generation_time_ms IS NOT NULL) as avg_generation_time_ms
            FROM mockups
            WHERE project_id = %s
            """,
            (project_id,),
        )
        row = cur.fetchone()

        if not row:
            return {
                "total": 0,
                "by_status": {},
                "unique_generators": 0,
                "avg_generation_time_ms": None,
            }

        return {
            "total": int(row[0]) if row[0] else 0,
            "by_status": {
                "generated": int(row[1]) if row[1] else 0,
                "pending_approval": int(row[2]) if row[2] else 0,
                "approved": int(row[3]) if row[3] else 0,
                "rejected": int(row[4]) if row[4] else 0,
                "applied": int(row[5]) if row[5] else 0,
                "archived": int(row[6]) if row[6] else 0,
            },
            "unique_generators": int(row[7]) if row[7] else 0,
            "avg_generation_time_ms": float(row[8]) if row[8] else None,
        }
