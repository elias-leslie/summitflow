"""Components storage layer - Component CRUD operations.

This module provides data access for TDD components (major parts of the system).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg import sql

from .connection import get_connection


def create_component(
    project_id: str,
    component_id: str,
    name: str,
    description: str | None = None,
    priority: int = 2,
    explorer_entry_id: int | None = None,
) -> dict[str, Any]:
    """Create a new component.

    Args:
        project_id: Project ID
        component_id: Unique component identifier (e.g., "auth", "api", "frontend")
        name: Human-readable component name
        description: Optional description
        priority: Priority 0-4 (0=critical, 4=backlog), default 2
        explorer_entry_id: Optional FK to explorer_entries

    Returns:
        The created component dict with all columns.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO components (project_id, component_id, name, description, priority,
                                    explorer_entry_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, component_id, name, description, priority, status,
                      created_at, updated_at, explorer_entry_id
            """,
            (project_id, component_id, name, description, priority, explorer_entry_id),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row)


def get_component(project_id: str, component_id: str) -> dict[str, Any] | None:
    """Get a component by project_id and component_id.

    Returns:
        Component dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, component_id, name, description, priority, status,
                   created_at, updated_at, explorer_entry_id
            FROM components
            WHERE project_id = %s AND component_id = %s
            """,
            (project_id, component_id),
        )
        row = cur.fetchone()

    return _row_to_dict(row) if row else None


def get_component_by_id(component_db_id: int) -> dict[str, Any] | None:
    """Get a component by database ID.

    Returns:
        Component dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, component_id, name, description, priority, status,
                   created_at, updated_at, explorer_entry_id
            FROM components
            WHERE id = %s
            """,
            (component_db_id,),
        )
        row = cur.fetchone()

    return _row_to_dict(row) if row else None


def list_components(project_id: str) -> list[dict[str, Any]]:
    """List all components for a project.

    Returns:
        List of component dicts, ordered by priority then name.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, component_id, name, description, priority, status,
                   created_at, updated_at, explorer_entry_id
            FROM components
            WHERE project_id = %s
            ORDER BY priority ASC, name ASC
            """,
            (project_id,),
        )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def update_component(
    project_id: str,
    component_id: str,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Update a component.

    Args:
        project_id: Project ID
        component_id: Component ID
        **kwargs: Fields to update (name, description, priority, status, explorer_entry_id)

    Returns:
        Updated component dict or None if not found.
    """
    allowed_fields = {"name", "description", "priority", "status", "explorer_entry_id"}
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}

    if not updates:
        return get_component(project_id, component_id)

    # Always update updated_at
    updates["updated_at"] = datetime.now(UTC)

    set_clauses = [sql.SQL("{} = %s").format(sql.Identifier(k)) for k in updates]
    values = [*list(updates.values()), project_id, component_id]

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("""
            UPDATE components
            SET {set_clause}
            WHERE project_id = %s AND component_id = %s
            RETURNING id, project_id, component_id, name, description, priority, status,
                      created_at, updated_at, explorer_entry_id
            """).format(set_clause=sql.SQL(", ").join(set_clauses)),
            values,
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row) if row else None


def delete_component(project_id: str, component_id: str) -> bool:
    """Delete a component.

    Returns:
        True if deleted, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM components
            WHERE project_id = %s AND component_id = %s
            RETURNING id
            """,
            (project_id, component_id),
        )
        deleted = cur.fetchone() is not None
        conn.commit()

    return deleted


def _row_to_dict(row: tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a dict."""
    if row is None:
        return {}

    return {
        "id": row[0],
        "project_id": row[1],
        "component_id": row[2],
        "name": row[3],
        "description": row[4],
        "priority": row[5],
        "status": row[6],
        "created_at": row[7].isoformat() if row[7] else None,
        "updated_at": row[8].isoformat() if row[8] else None,
        "explorer_entry_id": row[9] if len(row) > 9 else None,
    }
