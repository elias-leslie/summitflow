"""Storage layer for evidence regressions."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, TypedDict

from psycopg import sql
from psycopg.types.json import Jsonb

from .connection import get_connection

logger = logging.getLogger(__name__)


class EvidenceRegression(TypedDict, total=False):
    """Evidence regression record."""

    id: int
    evidence_id: int
    baseline_evidence_id: int | None
    regression_type: str
    pixel_diff_pct: float | None
    console_errors_added: int
    ai_analysis: dict[str, Any] | None
    severity: str
    status: str
    linked_task_id: str | None
    reviewed_at: datetime | None
    reviewed_by: str | None
    resolved_at: datetime | None
    created_at: datetime


def insert_regression(
    evidence_id: int,
    regression_type: str,
    *,
    baseline_evidence_id: int | None = None,
    pixel_diff_pct: float | None = None,
    console_errors_added: int = 0,
    ai_analysis: dict[str, Any] | None = None,
    severity: str = "unknown",
) -> EvidenceRegression:
    """Insert a new regression record."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evidence_regressions (
                evidence_id, baseline_evidence_id, regression_type,
                pixel_diff_pct, console_errors_added, ai_analysis, severity
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, evidence_id, baseline_evidence_id, regression_type,
                      pixel_diff_pct, console_errors_added, ai_analysis, severity,
                      status, linked_task_id, reviewed_at, reviewed_by, resolved_at, created_at
            """,
            (
                evidence_id,
                baseline_evidence_id,
                regression_type,
                pixel_diff_pct,
                console_errors_added,
                Jsonb(ai_analysis) if ai_analysis else None,
                severity,
            ),
        )
        row = cur.fetchone()
        conn.commit()

        if row is None:
            raise RuntimeError("Failed to insert regression")

        return _row_to_regression(row)


def get_unreviewed(project_id: str, *, limit: int = 50) -> list[EvidenceRegression]:
    """Get unreviewed regressions for a project."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.id, r.evidence_id, r.baseline_evidence_id, r.regression_type,
                   r.pixel_diff_pct, r.console_errors_added, r.ai_analysis, r.severity,
                   r.status, r.linked_task_id, r.reviewed_at, r.reviewed_by,
                   r.resolved_at, r.created_at
            FROM evidence_regressions r
            JOIN evidence e ON r.evidence_id = e.id
            WHERE e.project_id = %s AND r.status = 'detected'
            ORDER BY r.created_at DESC
            LIMIT %s
            """,
            (project_id, limit),
        )
        return [_row_to_regression(row) for row in cur.fetchall()]


def update_status(
    regression_id: int,
    status: str,
    *,
    reviewed_by: str | None = None,
    linked_task_id: str | None = None,
) -> EvidenceRegression | None:
    """Update regression status."""
    with get_connection() as conn, conn.cursor() as cur:
        # Build dynamic update
        updates = ["status = %s"]
        params: list[Any] = [status]

        if reviewed_by:
            updates.append("reviewed_at = NOW()")
            updates.append("reviewed_by = %s")
            params.append(reviewed_by)

        if linked_task_id:
            updates.append("linked_task_id = %s")
            params.append(linked_task_id)

        if status == "resolved":
            updates.append("resolved_at = NOW()")

        params.append(regression_id)

        # Build query using SQL composition for type safety
        query = sql.SQL(
            """
            UPDATE evidence_regressions
            SET {}
            WHERE id = %s
            RETURNING id, evidence_id, baseline_evidence_id, regression_type,
                      pixel_diff_pct, console_errors_added, ai_analysis, severity,
                      status, linked_task_id, reviewed_at, reviewed_by, resolved_at, created_at
            """
        ).format(sql.SQL(", ").join(sql.SQL(u) for u in updates))

        cur.execute(query, params)
        row = cur.fetchone()
        conn.commit()

        return _row_to_regression(row) if row else None


def link_task(regression_id: int, task_id: str) -> EvidenceRegression | None:
    """Link a regression to a task."""
    return update_status(regression_id, "linked", linked_task_id=task_id)


def _row_to_regression(row: tuple[Any, ...]) -> EvidenceRegression:
    """Convert database row to EvidenceRegression."""
    return {
        "id": row[0],
        "evidence_id": row[1],
        "baseline_evidence_id": row[2],
        "regression_type": row[3],
        "pixel_diff_pct": row[4],
        "console_errors_added": row[5] or 0,
        "ai_analysis": row[6],
        "severity": row[7],
        "status": row[8],
        "linked_task_id": row[9],
        "reviewed_at": row[10],
        "reviewed_by": row[11],
        "resolved_at": row[12],
        "created_at": row[13],
    }
