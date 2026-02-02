"""Helper utilities for explorer entries storage.

This module contains shared utilities used by explorer_entries.py:
- Row/data conversion helpers
- SQL query building utilities
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg import sql


def to_iso_string(value: datetime | None) -> str | None:
    """Convert datetime to ISO string, returning None if value is None."""
    return value.isoformat() if value else None


def build_where_clause(conditions: list[str]) -> sql.Composable:
    """Build a WHERE clause from a list of condition strings.

    Joins conditions with AND. If conditions is empty, returns TRUE.

    Args:
        conditions: List of condition strings like ["project_id = %s", "type = %s"]

    Returns:
        sql.Composable ready to format into a query
    """
    if conditions:
        return sql.SQL(" AND ").join(sql.SQL(c) for c in conditions)
    return sql.SQL("TRUE")


def row_to_entry(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert a database row to an entry dict."""
    return {
        "id": row[0],
        "project_id": row[1],
        "entry_type": row[2],
        "path": row[3],
        "name": row[4],
        "health_status": row[5],
        "metadata": row[6] if row[6] else {},
        "last_scanned_at": to_iso_string(row[7]),
        "created_at": to_iso_string(row[8]),
        "updated_at": to_iso_string(row[9]),
    }


# Standard column list for explorer_entries queries
ENTRY_COLUMNS = (
    "id, project_id, entry_type, path, name, health_status, "
    "metadata, last_scanned_at, created_at, updated_at"
)

# Allowed sort fields for get_entries queries
ALLOWED_SORT_FIELDS = {"path", "name", "health_status", "last_scanned_at", "created_at"}
