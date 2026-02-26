"""Scan history write operations - record_scan_start and record_scan_complete."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from ..connection import get_connection
from ._helpers import compute_metrics_delta, row_to_scan

_SCAN_COLUMNS = (
    "id, project_id, scan_type, triggered_by, triggered_by_session,"
    " triggered_by_user, trigger_context, started_at, completed_at,"
    " duration_ms, status, error_message, metrics, entries_found,"
    " entries_saved, previous_scan_id, metrics_delta, created_at"
)


def _get_previous_scan_id(cur: Any, project_id: str, scan_type: str) -> int | None:
    """Fetch the most recent completed scan ID for delta calculation."""
    cur.execute(
        """
        SELECT id FROM scan_history
        WHERE project_id = %s AND scan_type = %s AND status = 'completed'
        ORDER BY completed_at DESC LIMIT 1
        """,
        (project_id, scan_type),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _fetch_prev_metrics(
    cur: Any, previous_scan_id: int
) -> tuple[dict[str, Any], int, int]:
    """Fetch metrics from a previous scan."""
    cur.execute(
        "SELECT metrics, entries_found, entries_saved FROM scan_history WHERE id = %s",
        (previous_scan_id,),
    )
    row = cur.fetchone()
    if not row:
        return {}, 0, 0
    return row[0] or {}, row[1] or 0, row[2] or 0


def record_scan_start(
    project_id: str,
    scan_type: str,
    triggered_by: str = "manual",
    triggered_by_session: str | None = None,
    triggered_by_user: str | None = None,
    trigger_context: dict[str, Any] | None = None,
) -> int:
    """Record the start of a scan.

    Returns:
        Newly created scan_id
    """
    now = datetime.now(UTC)
    with get_connection() as conn, conn.cursor() as cur:
        previous_scan_id = _get_previous_scan_id(cur, project_id, scan_type)
        cur.execute(
            """
            INSERT INTO scan_history (
                project_id, scan_type, triggered_by, triggered_by_session,
                triggered_by_user, trigger_context, started_at, status, previous_scan_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'running', %s)
            RETURNING id
            """,
            (
                project_id, scan_type, triggered_by, triggered_by_session,
                triggered_by_user, json.dumps(trigger_context or {}),
                now, previous_scan_id,
            ),
        )
        row = cur.fetchone()
        conn.commit()
        return row[0] if row else 0


def record_scan_complete(
    scan_id: int,
    status: str = "completed",
    error_message: str | None = None,
    metrics: dict[str, Any] | None = None,
    entries_found: int = 0,
    entries_saved: int = 0,
) -> dict[str, Any] | None:
    """Record scan completion with metrics.

    Returns:
        Updated scan record or None if not found
    """
    now = datetime.now(UTC)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT started_at, previous_scan_id FROM scan_history WHERE id = %s",
            (scan_id,),
        )
        row = cur.fetchone()
        if not row:
            return None

        started_at, previous_scan_id = row[0], row[1]
        duration_ms = int((now - started_at).total_seconds() * 1000) if started_at else None

        metrics_delta: dict[str, Any] = {}
        if previous_scan_id and metrics:
            prev_metrics, prev_found, prev_saved = _fetch_prev_metrics(cur, previous_scan_id)
            metrics_delta = compute_metrics_delta(
                metrics, entries_found, entries_saved, prev_metrics, prev_found, prev_saved
            )

        cur.execute(
            f"""
            UPDATE scan_history
            SET status = %s, completed_at = %s, duration_ms = %s, error_message = %s,
                metrics = %s, entries_found = %s, entries_saved = %s, metrics_delta = %s
            WHERE id = %s
            RETURNING {_SCAN_COLUMNS}
            """,
            (
                status, now, duration_ms, error_message,
                json.dumps(metrics or {}), entries_found, entries_saved,
                json.dumps(metrics_delta), scan_id,
            ),
        )
        result = cur.fetchone()
        conn.commit()
        return row_to_scan(result) if result else None
