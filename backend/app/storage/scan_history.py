"""Scan history storage - Track scan executions with trigger metadata.

This module handles:
- Recording scan start (with trigger metadata)
- Recording scan completion (with metrics and delta calculation)
- Querying scan history and sparkline data
- Computing before/after scan comparisons
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from .connection import get_connection
from .explorer_entries import _to_iso_string


def record_scan_start(
    project_id: str,
    scan_type: str,
    triggered_by: str = "manual",
    triggered_by_session: str | None = None,
    triggered_by_user: str | None = None,
    trigger_context: dict[str, Any] | None = None,
) -> int:
    """Record the start of a scan.

    Args:
        project_id: Project ID for scoping
        scan_type: Type of scan ('file', 'page', 'endpoint', 'database', 'task', 'full')
        triggered_by: Source that initiated scan ('manual', 'refactor_it', etc.)
        triggered_by_session: Claude session ID if applicable
        triggered_by_user: User identifier if applicable
        trigger_context: Additional context about the trigger

    Returns:
        Newly created scan_id
    """
    now = datetime.now(UTC)

    with get_connection() as conn, conn.cursor() as cur:
        # Find previous scan for delta calculation
        cur.execute(
            """
            SELECT id FROM scan_history
            WHERE project_id = %s AND scan_type = %s AND status = 'completed'
            ORDER BY completed_at DESC
            LIMIT 1
            """,
            (project_id, scan_type),
        )
        prev_row = cur.fetchone()
        previous_scan_id = prev_row[0] if prev_row else None

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
                project_id,
                scan_type,
                triggered_by,
                triggered_by_session,
                triggered_by_user,
                json.dumps(trigger_context or {}),
                now,
                previous_scan_id,
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

    Args:
        scan_id: ID of the scan to complete
        status: Final status ('completed', 'failed', 'cancelled')
        error_message: Error message if status is 'failed'
        metrics: Type-specific metrics (files_scanned, errors_found, etc.)
        entries_found: Number of entries found during scan
        entries_saved: Number of entries saved/updated

    Returns:
        Updated scan record or None if not found
    """
    now = datetime.now(UTC)

    with get_connection() as conn, conn.cursor() as cur:
        # First get the scan to calculate duration
        cur.execute(
            """
            SELECT started_at, previous_scan_id FROM scan_history WHERE id = %s
            """,
            (scan_id,),
        )
        row = cur.fetchone()
        if not row:
            return None

        started_at = row[0]
        previous_scan_id = row[1]
        duration_ms = int((now - started_at).total_seconds() * 1000) if started_at else None

        # Calculate metrics delta if we have a previous scan
        metrics_delta: dict[str, Any] = {}
        if previous_scan_id and metrics:
            cur.execute(
                """
                SELECT metrics, entries_found, entries_saved FROM scan_history WHERE id = %s
                """,
                (previous_scan_id,),
            )
            prev_row = cur.fetchone()
            if prev_row:
                prev_metrics = prev_row[0] or {}
                prev_entries_found = prev_row[1] or 0
                prev_entries_saved = prev_row[2] or 0

                # Calculate deltas for common metrics
                metrics_delta = {
                    "entries_found": entries_found - prev_entries_found,
                    "entries_saved": entries_saved - prev_entries_saved,
                }
                # Add deltas for any numeric metrics
                for key in metrics:
                    if key in prev_metrics and isinstance(metrics[key], int | float):
                        metrics_delta[key] = metrics[key] - prev_metrics.get(key, 0)

        cur.execute(
            """
            UPDATE scan_history
            SET status = %s, completed_at = %s, duration_ms = %s, error_message = %s,
                metrics = %s, entries_found = %s, entries_saved = %s, metrics_delta = %s
            WHERE id = %s
            RETURNING id, project_id, scan_type, triggered_by, triggered_by_session,
                      triggered_by_user, trigger_context, started_at, completed_at,
                      duration_ms, status, error_message, metrics, entries_found,
                      entries_saved, previous_scan_id, metrics_delta, created_at
            """,
            (
                status,
                now,
                duration_ms,
                error_message,
                json.dumps(metrics or {}),
                entries_found,
                entries_saved,
                json.dumps(metrics_delta),
                scan_id,
            ),
        )
        result = cur.fetchone()
        conn.commit()

        if not result:
            return None

        return _row_to_scan(result)


def get_scan_history(
    project_id: str,
    days: int = 30,
    scan_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Get scan history for a project.

    Args:
        project_id: Project ID for scoping
        days: Number of days to look back (max 365)
        scan_type: Optional filter by scan type
        limit: Maximum number of records to return

    Returns:
        List of scan history records
    """
    days = min(days, 365)
    cutoff = datetime.now(UTC) - timedelta(days=days)

    with get_connection() as conn, conn.cursor() as cur:
        query = """
            SELECT id, project_id, scan_type, triggered_by, triggered_by_session,
                   triggered_by_user, trigger_context, started_at, completed_at,
                   duration_ms, status, error_message, metrics, entries_found,
                   entries_saved, previous_scan_id, metrics_delta, created_at
            FROM scan_history
            WHERE project_id = %s AND started_at >= %s
        """
        params: list[Any] = [project_id, cutoff]

        if scan_type:
            query += " AND scan_type = %s"
            params.append(scan_type)

        query += " ORDER BY started_at DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, params)
        return [_row_to_scan(row) for row in cur.fetchall()]


def get_scan_comparison(
    scan_id_before: int,
    scan_id_after: int,
) -> dict[str, Any] | None:
    """Get comparison between two scans.

    Args:
        scan_id_before: ID of the earlier scan
        scan_id_after: ID of the later scan

    Returns:
        Comparison dict with both scans and deltas, or None if scans not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, scan_type, triggered_by, triggered_by_session,
                   triggered_by_user, trigger_context, started_at, completed_at,
                   duration_ms, status, error_message, metrics, entries_found,
                   entries_saved, previous_scan_id, metrics_delta, created_at
            FROM scan_history
            WHERE id IN (%s, %s)
            """,
            (scan_id_before, scan_id_after),
        )
        rows = cur.fetchall()

        if len(rows) != 2:
            return None

        scans = {row[0]: _row_to_scan(row) for row in rows}
        before = scans.get(scan_id_before)
        after = scans.get(scan_id_after)

        if not before or not after:
            return None

        # Calculate deltas
        before_metrics = before.get("metrics", {})
        after_metrics = after.get("metrics", {})

        delta: dict[str, Any] = {
            "entries_found": after.get("entries_found", 0) - before.get("entries_found", 0),
            "entries_saved": after.get("entries_saved", 0) - before.get("entries_saved", 0),
        }

        delta_pct: dict[str, float] = {}

        # Calculate percentage changes for all numeric metrics
        all_keys = set(before_metrics.keys()) | set(after_metrics.keys())
        for key in all_keys:
            before_val = before_metrics.get(key, 0)
            after_val = after_metrics.get(key, 0)
            if isinstance(before_val, int | float) and isinstance(after_val, int | float):
                delta[key] = after_val - before_val
                if before_val != 0:
                    delta_pct[key] = round((after_val - before_val) / before_val * 100, 2)

        # Percentage for entries
        if before.get("entries_found", 0) > 0:
            delta_pct["entries_found"] = round(
                delta["entries_found"] / before["entries_found"] * 100, 2
            )

        return {
            "before_scan": before,
            "after_scan": after,
            "before_metrics": before_metrics,
            "after_metrics": after_metrics,
            "delta": delta,
            "delta_pct": delta_pct,
        }


def get_sparkline_data(
    project_id: str,
    days: int = 30,
) -> dict[str, Any]:
    """Get aggregated data for sparkline visualization.

    Args:
        project_id: Project ID for scoping
        days: Number of days to look back

    Returns:
        SparklineData dict with daily aggregations
    """
    days = min(days, 365)
    cutoff = datetime.now(UTC) - timedelta(days=days)

    with get_connection() as conn, conn.cursor() as cur:
        # Get daily aggregates
        cur.execute(
            """
            SELECT DATE(started_at) as scan_date,
                   COUNT(*) as scan_count,
                   AVG((metrics->>'complexity')::float) as avg_complexity,
                   SUM(CASE WHEN (metrics->>'high_priority_count')::int > 0 THEN 1 ELSE 0 END) as high_priority_count
            FROM scan_history
            WHERE project_id = %s AND started_at >= %s AND status = 'completed'
            GROUP BY DATE(started_at)
            ORDER BY scan_date
            """,
            (project_id, cutoff),
        )
        rows = cur.fetchall()

        dates: list[str] = []
        complexity: list[float | None] = []
        targets: list[int] = []
        high_priority: list[int] = []

        for row in rows:
            dates.append(row[0].strftime("%Y-%m-%d") if row[0] else "")
            complexity.append(float(row[2]) if row[2] else None)
            targets.append(int(row[1]) if row[1] else 0)
            high_priority.append(int(row[3]) if row[3] else 0)

        return {
            "dates": dates,
            "complexity": complexity,
            "targets": targets,
            "high_priority": high_priority,
        }


def get_summary(project_id: str, days: int = 30) -> dict[str, Any]:
    """Get summary statistics for scan history.

    Args:
        project_id: Project ID for scoping
        days: Number of days to look back

    Returns:
        ScanHistorySummary dict
    """
    days = min(days, 365)
    cutoff = datetime.now(UTC) - timedelta(days=days)

    with get_connection() as conn, conn.cursor() as cur:
        # Get overall stats
        cur.execute(
            """
            SELECT COUNT(*) as total_scans,
                   AVG(duration_ms) as avg_duration
            FROM scan_history
            WHERE project_id = %s AND started_at >= %s AND status = 'completed'
            """,
            (project_id, cutoff),
        )
        stats_row = cur.fetchone()
        total_scans = stats_row[0] if stats_row else 0
        avg_duration_ms = float(stats_row[1]) if stats_row and stats_row[1] else None

        # Get trigger breakdown
        cur.execute(
            """
            SELECT triggered_by, COUNT(*) as count
            FROM scan_history
            WHERE project_id = %s AND started_at >= %s
            GROUP BY triggered_by
            ORDER BY count DESC
            """,
            (project_id, cutoff),
        )
        trigger_rows = cur.fetchall()

        triggers_breakdown = []
        most_active_trigger = None
        for i, row in enumerate(trigger_rows):
            if i == 0:
                most_active_trigger = row[0]
            pct = round(row[1] / total_scans * 100, 1) if total_scans > 0 else 0.0
            triggers_breakdown.append({"trigger": row[0], "count": row[1], "percentage": pct})

        # Determine complexity trend (compare first vs last week)
        complexity_trend = "unknown"
        cur.execute(
            """
            WITH weekly AS (
                SELECT
                    CASE WHEN started_at >= NOW() - INTERVAL '7 days' THEN 'recent'
                         WHEN started_at >= NOW() - INTERVAL '14 days' THEN 'previous'
                    END as period,
                    AVG((metrics->>'complexity')::float) as avg_complexity
                FROM scan_history
                WHERE project_id = %s AND started_at >= NOW() - INTERVAL '14 days'
                      AND status = 'completed' AND metrics->>'complexity' IS NOT NULL
                GROUP BY period
            )
            SELECT * FROM weekly WHERE period IS NOT NULL
            """,
            (project_id,),
        )
        weekly_rows = cur.fetchall()
        weekly_data = {row[0]: row[1] for row in weekly_rows}

        if "recent" in weekly_data and "previous" in weekly_data:
            diff = weekly_data["recent"] - weekly_data["previous"]
            if diff < -0.1:
                complexity_trend = "improving"
            elif diff > 0.1:
                complexity_trend = "degrading"
            else:
                complexity_trend = "stable"

        return {
            "total_scans": total_scans,
            "avg_duration_ms": avg_duration_ms,
            "complexity_trend": complexity_trend,
            "most_active_trigger": most_active_trigger,
            "triggers_breakdown": triggers_breakdown,
        }


def _row_to_scan(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert a database row to a scan dict."""
    return {
        "id": row[0],
        "project_id": row[1],
        "scan_type": row[2],
        "triggered_by": row[3],
        "triggered_by_session": row[4],
        "triggered_by_user": row[5],
        "trigger_context": row[6] if row[6] else {},
        "started_at": _to_iso_string(row[7]),
        "completed_at": _to_iso_string(row[8]),
        "duration_ms": row[9],
        "status": row[10],
        "error_message": row[11],
        "metrics": row[12] if row[12] else {},
        "entries_found": row[13] or 0,
        "entries_saved": row[14] or 0,
        "previous_scan_id": row[15],
        "metrics_delta": row[16] if row[16] else {},
        "created_at": _to_iso_string(row[17]),
    }
