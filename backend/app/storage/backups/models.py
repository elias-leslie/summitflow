"""Data models and converters for backup operations."""

from __future__ import annotations

from typing import Any

# Base SELECT columns for backup queries
BACKUP_COLUMNS = """id, project_id, name, backup_type, status, size_bytes, db_size_bytes,
       files_size_bytes, location, note, created_at, started_at, completed_at, error_message,
       verified, verified_at, checksum, total_files, verification_json, source_id"""

EXPECTED_BACKUP_COLUMNS = 20


def row_to_backup(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert database row to backup dict.

    Args:
        row: Database row tuple with backup data

    Returns:
        Dictionary representation of backup record

    Raises:
        ValueError: If row has incorrect number of columns
    """
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
        "verified": row[14],
        "verified_at": row[15].isoformat() if row[15] else None,
        "checksum": row[16],
        "total_files": row[17],
        "verification_json": row[18],
        "source_id": row[19],
    }


def build_backup_updates(
    status: str,
    name: str | None = None,
    size_bytes: int | None = None,
    db_size_bytes: int | None = None,
    files_size_bytes: int | None = None,
    location: str | None = None,
    error_message: str | None = None,
    verified: bool | None = None,
    verified_at: str | None = None,
    checksum: str | None = None,
    total_files: int | None = None,
    verification_json: str | None = None,
) -> tuple[list[str], list[Any]]:
    """Build SQL UPDATE clauses and parameters for backup status update.

    Args:
        status: New backup status
        name: Actual archive name
        size_bytes: Total backup size
        db_size_bytes: Database dump size
        files_size_bytes: Project files size
        location: Backup storage location
        error_message: Error message if failed
        verified: Whether archive passed integrity checks
        verified_at: When verification was performed (ISO format)
        checksum: SHA256 checksum of the archive
        total_files: Number of files in the archive
        verification_json: Full verification output (JSON string)

    Returns:
        Tuple of (update_clauses, parameters)
    """
    updates = ["status = %s"]
    params: list[Any] = [status]

    if name is not None:
        updates.append("name = %s")
        params.append(name)

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

    if verified is not None:
        updates.append("verified = %s")
        params.append(verified)

    if verified_at is not None:
        updates.append("verified_at = %s")
        params.append(verified_at)

    if checksum is not None:
        updates.append("checksum = %s")
        params.append(checksum)

    if total_files is not None:
        updates.append("total_files = %s")
        params.append(total_files)

    if verification_json is not None:
        updates.append("verification_json = %s")
        params.append(verification_json)

    # Update timestamps based on status
    if status == "running":
        updates.append("started_at = NOW()")
    elif status in ("completed", "failed"):
        updates.append("completed_at = NOW()")

    return updates, params
