"""Explorer scan state storage - Scan state persistence.

This module handles:
- Getting current scan state
- Updating scan state
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .connection import get_connection, get_cursor
from .explorer_helpers import to_iso_string as _to_iso_string

_SCAN_STATE_COLUMNS = """
    project_id, status, current_type, types_total, types_completed,
    started_at, completed_at, error, results, updated_at
"""


def _row_to_scan_state(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert a DB row to a scan state dict.

    Args:
        row: Database row with 10 columns matching _SCAN_STATE_COLUMNS

    Returns:
        Scan state dict
    """
    return {
        "project_id": row[0],
        "status": row[1],
        "current_type": row[2],
        "types_total": row[3],
        "types_completed": row[4],
        "started_at": _to_iso_string(row[5]),
        "completed_at": _to_iso_string(row[6]),
        "error": row[7],
        "results": row[8] if row[8] else {},
        "updated_at": _to_iso_string(row[9]),
    }


def _build_scan_state_from_params(
    project_id: str,
    status: str,
    current_type: str | None,
    types_total: int,
    types_completed: int,
    started_at: datetime | None,
    completed_at: datetime | None,
    error: str | None,
    results: dict[str, Any] | None,
    updated_at: datetime,
) -> dict[str, Any]:
    """Build a scan state dict from individual parameters.

    Used as a fallback when RETURNING clause returns no row.

    Returns:
        Scan state dict
    """
    return {
        "project_id": project_id,
        "status": status,
        "current_type": current_type,
        "types_total": types_total,
        "types_completed": types_completed,
        "started_at": _to_iso_string(started_at),
        "completed_at": _to_iso_string(completed_at),
        "error": error,
        "results": results or {},
        "updated_at": _to_iso_string(updated_at),
    }


def get_scan_state(project_id: str) -> dict[str, Any] | None:
    """Get the current scan state for a project.

    Args:
        project_id: Project ID for scoping

    Returns:
        Scan state dict or None if no scan has been run
    """
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT {_SCAN_STATE_COLUMNS}
            FROM scan_states
            WHERE project_id = %s
            """,
            (project_id,),
        )
        row = cur.fetchone()

        if not row:
            return None

        return _row_to_scan_state(row)


def _upsert_scan_state_row(
    cur: Any,
    project_id: str,
    status: str,
    current_type: str | None,
    types_total: int,
    types_completed: int,
    started_at: datetime | None,
    completed_at: datetime | None,
    error: str | None,
    results: dict[str, Any] | None,
    now: datetime,
) -> tuple[Any, ...] | None:
    """Execute the scan state upsert and return the RETURNING row."""
    cur.execute(
        f"""
        INSERT INTO scan_states (
            {_SCAN_STATE_COLUMNS}
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (project_id)
        DO UPDATE SET
            status = EXCLUDED.status,
            current_type = EXCLUDED.current_type,
            types_total = EXCLUDED.types_total,
            types_completed = EXCLUDED.types_completed,
            started_at = EXCLUDED.started_at,
            completed_at = EXCLUDED.completed_at,
            error = EXCLUDED.error,
            results = EXCLUDED.results,
            updated_at = EXCLUDED.updated_at
        RETURNING {_SCAN_STATE_COLUMNS}
        """,
        (
            project_id,
            status,
            current_type,
            types_total,
            types_completed,
            started_at,
            completed_at,
            error,
            json.dumps(results or {}),
            now,
        ),
    )
    return cur.fetchone()


def update_scan_state(
    project_id: str,
    status: str,
    current_type: str | None = None,
    types_total: int = 0,
    types_completed: int = 0,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    error: str | None = None,
    results: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update (or create) the scan state for a project.

    Returns:
        Updated scan state dict
    """
    now = datetime.now(UTC)

    with get_connection() as conn, conn.cursor() as cur:
        row = _upsert_scan_state_row(
            cur,
            project_id,
            status,
            current_type,
            types_total,
            types_completed,
            started_at,
            completed_at,
            error,
            results,
            now,
        )
        conn.commit()

        if not row:
            # Should never happen with RETURNING, but satisfy type checker
            return _build_scan_state_from_params(
                project_id,
                status,
                current_type,
                types_total,
                types_completed,
                started_at,
                completed_at,
                error,
                results,
                now,
            )

        return _row_to_scan_state(row)
