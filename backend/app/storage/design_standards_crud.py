"""CRUD operations for design standards table.

Low-level database operations for design standards management.
"""

from typing import Any

from .connection import get_connection, get_cursor

# SQL constants
_STANDARD_COLS = (
    "id, project_id, name, description, base_standard_id, is_base, created_at, updated_at"
)


def _row_to_standard(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert database row to standard dict."""
    return {
        "id": row[0],
        "project_id": row[1],
        "name": row[2],
        "description": row[3],
        "base_standard_id": row[4],
        "is_base": row[5],
        "created_at": row[6],
        "updated_at": row[7],
    }


def get_base_standard() -> dict[str, Any] | None:
    """Get the base (global) design standard."""
    with get_cursor() as cur:
        cur.execute(
            f"SELECT {_STANDARD_COLS} FROM design_standards "
            "WHERE is_base = TRUE AND project_id IS NULL LIMIT 1"
        )
        row = cur.fetchone()
    return _row_to_standard(row) if row else None


def get_standard_by_id(standard_id: int) -> dict[str, Any] | None:
    """Get a design standard by ID."""
    with get_cursor() as cur:
        cur.execute(
            f"SELECT {_STANDARD_COLS} FROM design_standards WHERE id = %s",
            (standard_id,),
        )
        row = cur.fetchone()
    return _row_to_standard(row) if row else None


def get_project_standard(project_id: str, name: str | None = None) -> dict[str, Any] | None:
    """Get project-specific design standard."""
    with get_cursor() as cur:
        if name:
            cur.execute(
                f"SELECT {_STANDARD_COLS} FROM design_standards "
                "WHERE project_id = %s AND name = %s",
                (project_id, name),
            )
        else:
            cur.execute(
                f"SELECT {_STANDARD_COLS} FROM design_standards "
                "WHERE project_id = %s ORDER BY created_at ASC LIMIT 1",
                (project_id,),
            )
        row = cur.fetchone()
    return _row_to_standard(row) if row else None


def list_standards(project_id: str | None = None) -> list[dict[str, Any]]:
    """List design standards."""
    with get_cursor() as cur:
        if project_id:
            cur.execute(
                f"SELECT {_STANDARD_COLS} FROM design_standards "
                "WHERE project_id = %s OR (is_base = TRUE AND project_id IS NULL) "
                "ORDER BY is_base DESC, created_at ASC",
                (project_id,),
            )
        else:
            cur.execute(
                f"SELECT {_STANDARD_COLS} FROM design_standards "
                "WHERE is_base = TRUE AND project_id IS NULL ORDER BY created_at ASC"
            )
        rows = cur.fetchall()
    return [_row_to_standard(row) for row in rows]


def create_standard(
    name: str,
    description: str | None = None,
    project_id: str | None = None,
    base_standard_id: int | None = None,
    is_base: bool = False,
) -> dict[str, Any]:
    """Create a new design standard."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO design_standards (project_id, name, description, "
            f"base_standard_id, is_base, created_at, updated_at) "
            f"VALUES (%s, %s, %s, %s, %s, NOW(), NOW()) RETURNING {_STANDARD_COLS}",
            (project_id, name, description, base_standard_id, is_base),
        )
        row = cur.fetchone()
        conn.commit()
    if not row:
        raise ValueError("Failed to create design standard")
    return _row_to_standard(row)


def update_standard(
    standard_id: int,
    name: str | None = None,
    description: str | None = None,
) -> dict[str, Any] | None:
    """Update a design standard."""
    updates = []
    params: list[Any] = []
    if name is not None:
        updates.append("name = %s")
        params.append(name)
    if description is not None:
        updates.append("description = %s")
        params.append(description)
    if not updates:
        return get_standard_by_id(standard_id)
    updates.append("updated_at = NOW()")
    params.append(standard_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE design_standards SET {', '.join(updates)} "
            f"WHERE id = %s RETURNING {_STANDARD_COLS}",
            params,
        )
        row = cur.fetchone()
        conn.commit()
    return _row_to_standard(row) if row else None


def delete_standard(standard_id: int) -> bool:
    """Delete a design standard and its rules."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM design_standards WHERE id = %s RETURNING id",
            (standard_id,),
        )
        row = cur.fetchone()
        conn.commit()
    return row is not None
