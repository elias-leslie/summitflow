"""CRUD operations for backup sources."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..connection import get_connection

SOURCE_COLUMNS = """id, name, path, source_type, project_id, enabled, frequency,
       retention_days, last_run_at, next_run_at, created_at, updated_at"""

EXPECTED_SOURCE_COLUMNS = 12


def row_to_source(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert database row to source dict."""
    if len(row) != EXPECTED_SOURCE_COLUMNS:
        raise ValueError(f"Expected {EXPECTED_SOURCE_COLUMNS} columns, got {len(row)}")
    return {
        "id": row[0],
        "name": row[1],
        "path": row[2],
        "source_type": row[3],
        "project_id": row[4],
        "enabled": row[5],
        "frequency": row[6],
        "retention_days": row[7],
        "last_run_at": row[8].isoformat() if row[8] else None,
        "next_run_at": row[9].isoformat() if row[9] else None,
        "created_at": row[10].isoformat() if row[10] else None,
        "updated_at": row[11].isoformat() if row[11] else None,
    }


def list_sources(source_type: str | None = None) -> list[dict[str, Any]]:
    """List all backup sources, optionally filtered by type."""
    where = "WHERE source_type = %s" if source_type else ""
    params = [source_type] if source_type else []

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {SOURCE_COLUMNS} FROM backup_sources {where} ORDER BY source_type, name",
            params,
        )
        rows = cur.fetchall()

    return [row_to_source(row) for row in rows]


def get_source(source_id: str) -> dict[str, Any] | None:
    """Get a single backup source by ID."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {SOURCE_COLUMNS} FROM backup_sources WHERE id = %s",
            (source_id,),
        )
        row = cur.fetchone()

    return row_to_source(row) if row else None


def create_source(
    source_id: str,
    name: str,
    path: str,
    source_type: str = "project",
    project_id: str | None = None,
) -> dict[str, Any]:
    """Register a new backup source."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO backup_sources (id, name, path, source_type, project_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING {SOURCE_COLUMNS}
            """,
            (source_id, name, path, source_type, project_id),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        raise RuntimeError("Failed to create backup source")
    return row_to_source(row)


def update_source(source_id: str, **fields: Any) -> dict[str, Any] | None:
    """Update a backup source. Accepts: name, enabled, frequency, retention_days, path."""
    allowed = {"name", "enabled", "frequency", "retention_days", "path"}
    updates = []
    params: list[Any] = []

    unknown = fields.keys() - allowed
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")

    for key, value in fields.items():
        updates.append(f"{key} = %s")
        params.append(value)

    if not updates:
        return get_source(source_id)

    updates.append("updated_at = NOW()")
    params.append(source_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE backup_sources SET {', '.join(updates)} WHERE id = %s RETURNING {SOURCE_COLUMNS}",
            params,
        )
        row = cur.fetchone()
        conn.commit()

    return row_to_source(row) if row else None


def delete_source(source_id: str) -> bool:
    """Delete a backup source."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM backup_sources WHERE id = %s RETURNING id", (source_id,))
        row = cur.fetchone()
        conn.commit()

    return row is not None


def list_due_sources() -> list[dict[str, Any]]:
    """Get all sources that are due for a scheduled backup."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {SOURCE_COLUMNS} FROM backup_sources
            WHERE enabled = TRUE AND (next_run_at IS NULL OR next_run_at <= NOW())
            ORDER BY next_run_at ASC NULLS FIRST
            """
        )
        rows = cur.fetchall()

    return [row_to_source(row) for row in rows]


def update_source_last_run(source_id: str, next_run_at: datetime | None = None) -> bool:
    """Update source after a backup run."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE backup_sources
            SET last_run_at = NOW(), next_run_at = %s, updated_at = NOW()
            WHERE id = %s
            RETURNING id
            """,
            (next_run_at, source_id),
        )
        row = cur.fetchone()
        conn.commit()

    return row is not None
