"""Backup Storage - Database operations for backup management.

This module handles all database interactions for backup records:
- CRUD operations for backups
- Backup status tracking
- Schedule configuration
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .connection import generate_prefixed_id, get_connection

# Base SELECT columns for backup queries
BACKUP_COLUMNS = """id, project_id, name, backup_type, status, size_bytes, db_size_bytes,
       files_size_bytes, location, note, created_at, started_at, completed_at, error_message"""

BACKUP_SCHEDULE_COLUMNS = """id, project_id, enabled, frequency, retention_count,
       last_run_at, next_run_at, created_at, updated_at"""

EXPECTED_BACKUP_COLUMNS = 14
EXPECTED_SCHEDULE_COLUMNS = 9


def _generate_backup_id() -> str:
    return generate_prefixed_id("bkp")


def _row_to_backup(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert database row to backup dict."""
    if len(row) != EXPECTED_BACKUP_COLUMNS:
        raise ValueError(f"Expected {EXPECTED_BACKUP_COLUMNS} columns, got {len(row)}")
    return {
        "id": row[0],
        "project_id": row[1],
        "name": row[2],
        "backup_type": row[3],
        "status": row[4],
        "size_bytes": row[5],
        "db_size_bytes": row[6],
        "files_size_bytes": row[7],
        "location": row[8],
        "note": row[9],
        "created_at": row[10].isoformat() if row[10] else None,
        "started_at": row[11].isoformat() if row[11] else None,
        "completed_at": row[12].isoformat() if row[12] else None,
        "error_message": row[13],
    }


def _row_to_schedule(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert database row to schedule dict."""
    if len(row) != EXPECTED_SCHEDULE_COLUMNS:
        raise ValueError(f"Expected {EXPECTED_SCHEDULE_COLUMNS} columns, got {len(row)}")
    return {
        "id": row[0],
        "project_id": row[1],
        "enabled": row[2],
        "frequency": row[3],
        "retention_count": row[4],
        "last_run_at": row[5].isoformat() if row[5] else None,
        "next_run_at": row[6].isoformat() if row[6] else None,
        "created_at": row[7].isoformat() if row[7] else None,
        "updated_at": row[8].isoformat() if row[8] else None,
    }


# ============================================================
# Backup CRUD Operations
# ============================================================


def create_backup_record(
    project_id: str,
    backup_type: str = "manual",
    note: str | None = None,
) -> dict[str, Any]:
    """Create a new backup record in pending status.

    Args:
        project_id: Project ID
        backup_type: 'manual' or 'scheduled'
        note: Optional user note

    Returns:
        Created backup record
    """
    backup_id = _generate_backup_id()
    name = f"{project_id}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO backups (id, project_id, name, backup_type, status, note)
            VALUES (%s, %s, %s, %s, 'pending', %s)
            RETURNING {BACKUP_COLUMNS}
            """,
            (backup_id, project_id, name, backup_type, note),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        raise RuntimeError("Failed to create backup record")
    return _row_to_backup(row)


def get_backup(backup_id: str) -> dict[str, Any] | None:
    """Get a backup by ID."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {BACKUP_COLUMNS} FROM backups WHERE id = %s",
            (backup_id,),
        )
        row = cur.fetchone()

    return _row_to_backup(row) if row else None


def list_backups(
    project_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List backups with optional filtering.

    Args:
        project_id: Filter by project (None for all projects)
        limit: Max records to return
        offset: Pagination offset
        status: Filter by status

    Returns:
        Tuple of (backups, total_count)
    """
    where_clauses = []
    params: list[Any] = []

    if project_id:
        where_clauses.append("project_id = %s")
        params.append(project_id)

    if status:
        where_clauses.append("status = %s")
        params.append(status)

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    with get_connection() as conn, conn.cursor() as cur:
        # Get total count
        cur.execute(f"SELECT COUNT(*) FROM backups WHERE {where_sql}", params)
        count_row = cur.fetchone()
        total = int(count_row[0]) if count_row else 0

        # Get paginated results
        cur.execute(
            f"SELECT {BACKUP_COLUMNS} FROM backups WHERE {where_sql} "
            "ORDER BY created_at DESC LIMIT %s OFFSET %s",
            [*params, limit, offset],
        )
        rows = cur.fetchall()

    return [_row_to_backup(row) for row in rows], total


def update_backup_status(
    backup_id: str,
    status: str,
    size_bytes: int | None = None,
    db_size_bytes: int | None = None,
    files_size_bytes: int | None = None,
    location: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any] | None:
    """Update backup status and optional fields.

    Args:
        backup_id: Backup ID
        status: New status ('pending', 'running', 'completed', 'failed')
        size_bytes: Total backup size
        db_size_bytes: Database dump size
        files_size_bytes: Project files size
        location: Backup storage location
        error_message: Error message if failed

    Returns:
        Updated backup record or None if not found
    """
    updates = ["status = %s"]
    params: list[Any] = [status]

    if size_bytes is not None:
        updates.append("size_bytes = %s")
        params.append(size_bytes)

    if db_size_bytes is not None:
        updates.append("db_size_bytes = %s")
        params.append(db_size_bytes)

    if files_size_bytes is not None:
        updates.append("files_size_bytes = %s")
        params.append(files_size_bytes)

    if location is not None:
        updates.append("location = %s")
        params.append(location)

    if error_message is not None:
        updates.append("error_message = %s")
        params.append(error_message)

    # Update timestamps based on status
    if status == "running":
        updates.append("started_at = NOW()")
    elif status in ("completed", "failed"):
        updates.append("completed_at = NOW()")

    params.append(backup_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE backups SET {', '.join(updates)} WHERE id = %s RETURNING {BACKUP_COLUMNS}",
            params,
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_backup(row) if row else None


def delete_backup_record(backup_id: str) -> bool:
    """Delete a backup record.

    Args:
        backup_id: Backup ID

    Returns:
        True if deleted, False if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM backups WHERE id = %s RETURNING id", (backup_id,))
        row = cur.fetchone()
        conn.commit()

    return row is not None


# ============================================================
# Schedule CRUD Operations
# ============================================================


def get_schedule(project_id: str) -> dict[str, Any] | None:
    """Get backup schedule for a project."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {BACKUP_SCHEDULE_COLUMNS} FROM backup_schedules WHERE project_id = %s",
            (project_id,),
        )
        row = cur.fetchone()

    return _row_to_schedule(row) if row else None


def upsert_schedule(
    project_id: str,
    enabled: bool,
    frequency: str,
    retention_count: int = 5,
) -> dict[str, Any]:
    """Create or update backup schedule for a project.

    Args:
        project_id: Project ID
        enabled: Whether schedule is active
        frequency: 'daily', 'weekly', or 'monthly'
        retention_count: Number of backups to retain

    Returns:
        Schedule record
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO backup_schedules (project_id, enabled, frequency, retention_count)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (project_id) DO UPDATE SET
                enabled = EXCLUDED.enabled,
                frequency = EXCLUDED.frequency,
                retention_count = EXCLUDED.retention_count,
                updated_at = NOW()
            RETURNING {BACKUP_SCHEDULE_COLUMNS}
            """,
            (project_id, enabled, frequency, retention_count),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        raise RuntimeError("Failed to upsert schedule")
    return _row_to_schedule(row)


def update_schedule_last_run(project_id: str, next_run_at: datetime | None = None) -> bool:
    """Update schedule after a run.

    Args:
        project_id: Project ID
        next_run_at: Next scheduled run time

    Returns:
        True if updated, False if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE backup_schedules
            SET last_run_at = NOW(), next_run_at = %s, updated_at = NOW()
            WHERE project_id = %s
            RETURNING id
            """,
            (next_run_at, project_id),
        )
        row = cur.fetchone()
        conn.commit()

    return row is not None


def list_due_schedules() -> list[dict[str, Any]]:
    """Get all schedules that are due to run.

    Returns:
        List of schedule records where next_run_at <= NOW() and enabled = true
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {BACKUP_SCHEDULE_COLUMNS} FROM backup_schedules
            WHERE enabled = TRUE AND (next_run_at IS NULL OR next_run_at <= NOW())
            ORDER BY next_run_at ASC NULLS FIRST
            """
        )
        rows = cur.fetchall()

    return [_row_to_schedule(row) for row in rows]


# ============================================================
# Aggregation Functions
# ============================================================


def get_storage_summary(project_id: str | None = None) -> dict[str, Any]:
    """Get storage usage summary.

    Args:
        project_id: Filter by project (None for all)

    Returns:
        Storage summary with total_bytes, backup_count, by_status
    """
    where_clause = "WHERE project_id = %s" if project_id else ""
    params = [project_id] if project_id else []

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                COUNT(*) as total_count,
                COALESCE(SUM(size_bytes), 0) as total_bytes,
                COUNT(*) FILTER (WHERE status = 'completed') as completed_count,
                COUNT(*) FILTER (WHERE status = 'pending') as pending_count,
                COUNT(*) FILTER (WHERE status = 'running') as running_count,
                COUNT(*) FILTER (WHERE status = 'failed') as failed_count
            FROM backups
            {where_clause}
            """,
            params,
        )
        row = cur.fetchone()

    if not row:
        return {
            "total_count": 0,
            "total_bytes": 0,
            "by_status": {},
        }

    by_status: dict[str, int] = {}
    if row[2]:
        by_status["completed"] = int(row[2])
    if row[3]:
        by_status["pending"] = int(row[3])
    if row[4]:
        by_status["running"] = int(row[4])
    if row[5]:
        by_status["failed"] = int(row[5])

    return {
        "total_count": int(row[0]) if row[0] else 0,
        "total_bytes": int(row[1]) if row[1] else 0,
        "by_status": by_status,
    }


def get_latest_backup(project_id: str) -> dict[str, Any] | None:
    """Get the most recent completed backup for a project."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {BACKUP_COLUMNS} FROM backups "
            "WHERE project_id = %s AND status = 'completed' "
            "ORDER BY completed_at DESC LIMIT 1",
            (project_id,),
        )
        row = cur.fetchone()

    return _row_to_backup(row) if row else None
