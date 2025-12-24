"""Capabilities storage layer - Capability CRUD operations.

This module provides data access for TDD capabilities (what must work in a component).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg import sql

from .connection import get_connection


def create_capability(
    project_id: str,
    component_id: int,
    capability_id: str,
    name: str,
    description: str | None = None,
    priority: int = 2,
) -> dict[str, Any]:
    """Create a new capability.

    Args:
        project_id: Project ID
        component_id: Database ID of the parent component
        capability_id: Unique capability identifier (e.g., "login", "password-reset")
        name: Human-readable capability name
        description: Optional description
        priority: Priority 0-4 (0=critical, 4=backlog), default 2

    Returns:
        The created capability dict with all columns.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO capabilities (project_id, component_id, capability_id, name, description, priority)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, component_id, capability_id, name, description,
                      priority, status, locked_at, created_at, updated_at
            """,
            (project_id, component_id, capability_id, name, description, priority),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row)


def get_capability(project_id: str, capability_id: str) -> dict[str, Any] | None:
    """Get a capability by project_id and capability_id.

    Returns:
        Capability dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, component_id, capability_id, name, description,
                   priority, status, locked_at, created_at, updated_at
            FROM capabilities
            WHERE project_id = %s AND capability_id = %s
            """,
            (project_id, capability_id),
        )
        row = cur.fetchone()

    return _row_to_dict(row) if row else None


def get_capability_by_id(capability_db_id: int) -> dict[str, Any] | None:
    """Get a capability by database ID.

    Returns:
        Capability dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, component_id, capability_id, name, description,
                   priority, status, locked_at, created_at, updated_at
            FROM capabilities
            WHERE id = %s
            """,
            (capability_db_id,),
        )
        row = cur.fetchone()

    return _row_to_dict(row) if row else None


def list_capabilities(
    project_id: str,
    component_id: int | None = None,
) -> list[dict[str, Any]]:
    """List capabilities for a project, optionally filtered by component.

    Args:
        project_id: Project ID
        component_id: Optional component database ID to filter by

    Returns:
        List of capability dicts, ordered by priority then name.
    """
    with get_connection() as conn, conn.cursor() as cur:
        if component_id is not None:
            cur.execute(
                """
                SELECT id, project_id, component_id, capability_id, name, description,
                       priority, status, locked_at, created_at, updated_at
                FROM capabilities
                WHERE project_id = %s AND component_id = %s
                ORDER BY priority ASC, name ASC
                """,
                (project_id, component_id),
            )
        else:
            cur.execute(
                """
                SELECT id, project_id, component_id, capability_id, name, description,
                       priority, status, locked_at, created_at, updated_at
                FROM capabilities
                WHERE project_id = %s
                ORDER BY priority ASC, name ASC
                """,
                (project_id,),
            )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def update_capability(
    project_id: str,
    capability_id: str,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Update a capability.

    Args:
        project_id: Project ID
        capability_id: Capability ID
        **kwargs: Fields to update (name, description, priority, status)

    Returns:
        Updated capability dict or None if not found.
    """
    allowed_fields = {"name", "description", "priority", "status"}
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}

    if not updates:
        return get_capability(project_id, capability_id)

    # Always update updated_at
    updates["updated_at"] = datetime.now(UTC)

    set_clauses = [sql.SQL("{} = %s").format(sql.Identifier(k)) for k in updates]
    values = [*list(updates.values()), project_id, capability_id]

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("""
            UPDATE capabilities
            SET {set_clause}
            WHERE project_id = %s AND capability_id = %s
            RETURNING id, project_id, component_id, capability_id, name, description,
                      priority, status, locked_at, created_at, updated_at
            """).format(set_clause=sql.SQL(", ").join(set_clauses)),
            values,
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row) if row else None


def lock_capability(project_id: str, capability_id: str) -> dict[str, Any] | None:
    """Lock a capability (mark as verified/frozen).

    Sets locked_at timestamp and status to 'locked'.

    Returns:
        Updated capability dict or None if not found.
    """
    now = datetime.now(UTC)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE capabilities
            SET locked_at = %s, status = 'locked', updated_at = %s
            WHERE project_id = %s AND capability_id = %s
            RETURNING id, project_id, component_id, capability_id, name, description,
                      priority, status, locked_at, created_at, updated_at
            """,
            (now, now, project_id, capability_id),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row) if row else None


def unlock_capability(project_id: str, capability_id: str) -> dict[str, Any] | None:
    """Unlock a capability (remove lock).

    Clears locked_at timestamp and sets status to 'pending'.

    Returns:
        Updated capability dict or None if not found.
    """
    now = datetime.now(UTC)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE capabilities
            SET locked_at = NULL, status = 'pending', updated_at = %s
            WHERE project_id = %s AND capability_id = %s
            RETURNING id, project_id, component_id, capability_id, name, description,
                      priority, status, locked_at, created_at, updated_at
            """,
            (now, project_id, capability_id),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row) if row else None


def delete_capability(project_id: str, capability_id: str) -> bool:
    """Delete a capability.

    Returns:
        True if deleted, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM capabilities
            WHERE project_id = %s AND capability_id = %s
            RETURNING id
            """,
            (project_id, capability_id),
        )
        deleted = cur.fetchone() is not None
        conn.commit()

    return deleted


def _row_to_dict(row: tuple | None) -> dict[str, Any]:
    """Convert a database row to a dict."""
    if row is None:
        return {}

    return {
        "id": row[0],
        "project_id": row[1],
        "component_id": row[2],
        "capability_id": row[3],
        "name": row[4],
        "description": row[5],
        "priority": row[6],
        "status": row[7],
        "locked_at": row[8].isoformat() if row[8] else None,
        "created_at": row[9].isoformat() if row[9] else None,
        "updated_at": row[10].isoformat() if row[10] else None,
    }
