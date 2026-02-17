"""Explorer scan state storage - Scan state persistence.

This module handles:
- Getting current scan state
- Updating scan state
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .connection import get_connection
from .explorer_helpers import to_iso_string as _to_iso_string


def get_scan_state(project_id: str) -> dict[str, Any] | None:
    """Get the current scan state for a project.

    Args:
        project_id: Project ID for scoping

    Returns:
        Scan state dict or None if no scan has been run
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT project_id, status, current_type, types_total, types_completed,
                   started_at, completed_at, error, results, updated_at
            FROM scan_states
            WHERE project_id = %s
            """,
            (project_id,),
        )
        row = cur.fetchone()

        if not row:
            return None

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

    Args:
        project_id: Project ID for scoping
        status: Scan status ('idle', 'running', 'completed', 'failed')
        current_type: Currently scanning type
        types_total: Total number of types to scan
        types_completed: Number of types completed
        started_at: When the scan started
        completed_at: When the scan completed
        error: Error message if failed
        results: Scan results (counts per type)

    Returns:
        Updated scan state dict
    """
    now = datetime.now(UTC)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scan_states (
                project_id, status, current_type, types_total, types_completed,
                started_at, completed_at, error, results, updated_at
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
            RETURNING project_id, status, current_type, types_total, types_completed,
                      started_at, completed_at, error, results, updated_at
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
        row = cur.fetchone()
        conn.commit()

        if not row:
            # Should never happen with RETURNING, but satisfy type checker
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
                "updated_at": _to_iso_string(now),
            }

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
