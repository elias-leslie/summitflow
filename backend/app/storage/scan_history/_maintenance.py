"""Maintenance helpers for scan history retention and stale-run recovery."""

from __future__ import annotations

from typing import Any

from .._sql import static_sql
from ..connection import get_connection


def _table_exists(cur: Any, table_name: str) -> bool:
    """Return True when a referenced table exists in the public schema."""
    cur.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
    row = cur.fetchone()
    return bool(row and row[0])


def fail_stale_running_scans(max_age_hours: int = 6) -> int:
    """Mark scans as failed when they have been stuck in running state too long."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE scan_history
            SET status = 'failed',
                completed_at = NOW(),
                duration_ms = GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000))::integer,
                error_message = CASE
                    WHEN COALESCE(error_message, '') = ''
                        THEN 'Auto-failed by maintenance: stale running scan exceeded retention window.'
                    ELSE error_message
                END
            WHERE status = 'running'
              AND started_at < NOW() - (%s * INTERVAL '1 hour')
            """,
            (max_age_hours,),
        )
        count = cur.rowcount
        # scan_states is the gate ensure_scan_not_running checks; a row stuck in
        # 'running' blocks every future scan for that project, so recover it too.
        cur.execute(
            """
            UPDATE scan_states
            SET status = 'failed',
                completed_at = NOW(),
                error = CASE
                    WHEN COALESCE(error, '') = ''
                        THEN 'Auto-failed by maintenance: stale running scan exceeded retention window.'
                    ELSE error
                END,
                updated_at = NOW()
            WHERE status = 'running'
              AND started_at < NOW() - (%s * INTERVAL '1 hour')
            """,
            (max_age_hours,),
        )
        count += cur.rowcount
        conn.commit()

    return count


def cleanup_old_scan_history(
    *,
    max_age_days: int = 90,
    keep_latest_per_type: int = 20,
) -> int:
    """Delete old scan rows that are no longer referenced elsewhere."""
    with get_connection() as conn, conn.cursor() as cur:
        reference_clauses = [
            """
            NOT EXISTS (
                SELECT 1 FROM scan_history child WHERE child.previous_scan_id = sh.id
            )
            """
        ]
        if _table_exists(cur, "refactor_sessions"):
            reference_clauses.append(
                """
                NOT EXISTS (
                    SELECT 1 FROM refactor_sessions rs
                    WHERE rs.baseline_scan_id = sh.id OR rs.final_scan_id = sh.id
                )
                """
            )
        if _table_exists(cur, "qa_issues"):
            reference_clauses.append(
                """
                NOT EXISTS (
                    SELECT 1 FROM qa_issues qi
                    WHERE qi.detected_in_scan_id = sh.id OR qi.resolution_scan_id = sh.id
                )
                """
            )

        # SAFETY: reference_clauses contains only hardcoded SQL literals assembled above;
        # it must never include user-supplied input to avoid SQL injection.
        reference_sql = " AND ".join(clause.strip() for clause in reference_clauses)
        cur.execute(
            static_sql(
                f"""
                WITH ranked AS (
                    SELECT
                        sh.id,
                        ROW_NUMBER() OVER (
                            PARTITION BY sh.project_id, sh.scan_type
                            ORDER BY sh.started_at DESC, sh.id DESC
                        ) AS rn
                    FROM scan_history sh
                    WHERE sh.status != 'running'
                ),
                candidates AS (
                    SELECT sh.id
                    FROM scan_history sh
                    JOIN ranked r ON r.id = sh.id
                    WHERE r.rn > %s
                      AND sh.started_at < NOW() - (%s * INTERVAL '1 day')
                      AND {reference_sql}
                ),
                deleted AS (
                    DELETE FROM scan_history
                    WHERE id IN (SELECT id FROM candidates)
                    RETURNING id
                )
                SELECT COUNT(*) FROM deleted
                """
            ),
            (keep_latest_per_type, max_age_days),
        )
        row = cur.fetchone()
        conn.commit()

    return int(row[0] or 0) if row else 0
