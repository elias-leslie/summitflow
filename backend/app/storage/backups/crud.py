"""CRUD operations for backup records."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from ..connection import generate_prefixed_id, get_connection
from .models import BACKUP_COLUMNS, build_backup_updates, row_to_backup


def generate_backup_id() -> str:
    """Generate a new backup ID with 'bkp' prefix.

    Returns:
        Backup ID string (e.g., 'bkp-1234567890')
    """
    return generate_prefixed_id("bkp")


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

    Raises:
        RuntimeError: If record creation fails
    """
    backup_id = generate_backup_id()
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
    return row_to_backup(row)


def get_backup(backup_id: str) -> dict[str, Any] | None:
    """Get a backup by ID.

    Args:
        backup_id: Backup ID

    Returns:
        Backup record or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {BACKUP_COLUMNS} FROM backups WHERE id = %s",
            (backup_id,),
        )
        row = cur.fetchone()

    return row_to_backup(row) if row else None


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

    return [row_to_backup(row) for row in rows], total


def update_backup_status(
    backup_id: str,
    status: str,
    size_bytes: int | None = None,
    db_size_bytes: int | None = None,
    files_size_bytes: int | None = None,
    location: str | None = None,
    error_message: str | None = None,
    verified: bool | None = None,
    verified_at: str | None = None,
    checksum: str | None = None,
    total_files: int | None = None,
    verification_json: dict[str, Any] | None = None,
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
        verified: Whether archive passed integrity checks
        verified_at: When verification was performed (ISO format)
        checksum: SHA256 checksum of the archive
        total_files: Number of files in the archive
        verification_json: Full verification output (tree, errors, etc.)

    Returns:
        Updated backup record or None if not found
    """
    verification_json_str = json.dumps(verification_json) if verification_json else None
    updates, params = build_backup_updates(
        status=status,
        size_bytes=size_bytes,
        db_size_bytes=db_size_bytes,
        files_size_bytes=files_size_bytes,
        location=location,
        error_message=error_message,
        verified=verified,
        verified_at=verified_at,
        checksum=checksum,
        total_files=total_files,
        verification_json=verification_json_str,
    )

    params.append(backup_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE backups SET {', '.join(updates)} WHERE id = %s RETURNING {BACKUP_COLUMNS}",
            params,
        )
        row = cur.fetchone()
        conn.commit()

    return row_to_backup(row) if row else None


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
