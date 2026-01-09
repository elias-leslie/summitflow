"""Regression detection review endpoints.

Review and manage detected evidence regressions.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


class RegressionListItem(BaseModel):
    """A regression item for the list endpoint."""

    id: int
    evidence_id: int
    baseline_evidence_id: int | None
    regression_type: str
    pixel_diff_pct: float | None
    console_errors_added: int
    severity: str
    status: str
    linked_task_id: str | None
    created_at: str


class RegressionReviewRequest(BaseModel):
    """Request to review a regression."""

    verdict: str = Field(
        ...,
        description="Verdict: 'accept_change' (intentional) or 'confirm_regression' (bug)",
    )
    notes: str | None = Field(None, description="Optional review notes")


@router.get("/projects/{project_id}/evidence/regressions")
async def list_regressions(
    project_id: str,
    status: str | None = Query(None, description="Filter: detected, reviewed, resolved"),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """List regressions for a project.

    Filters by status if provided.
    """
    from ...storage import evidence_regressions
    from ...storage.connection import get_connection

    formatted_regressions: list[dict[str, Any]] = []

    if status == "detected" or status is None:
        unreviewed = evidence_regressions.get_unreviewed(project_id, limit=limit)
        for r in unreviewed:
            created_at = r.get("created_at")
            created_at_str = ""
            if created_at is not None and hasattr(created_at, "isoformat"):
                created_at_str = created_at.isoformat()
            elif created_at is not None:
                created_at_str = str(created_at)

            formatted_regressions.append(
                RegressionListItem(
                    id=r.get("id", 0),
                    evidence_id=r.get("evidence_id", 0),
                    baseline_evidence_id=r.get("baseline_evidence_id"),
                    regression_type=r.get("regression_type", "unknown"),
                    pixel_diff_pct=r.get("pixel_diff_pct"),
                    console_errors_added=r.get("console_errors_added", 0),
                    severity=r.get("severity", "unknown"),
                    status=r.get("status", "detected"),
                    linked_task_id=r.get("linked_task_id"),
                    created_at=created_at_str,
                ).model_dump()
            )

    if status is None or status in ("reviewed", "resolved"):
        with get_connection() as conn, conn.cursor() as cur:
            status_filter = "" if status is None else "AND r.status = %s"
            params: list[Any] = [project_id, limit]
            if status:
                params.insert(1, status)

            cur.execute(
                f"""
                SELECT r.id, r.evidence_id, r.baseline_evidence_id, r.regression_type,
                       r.pixel_diff_pct, r.console_errors_added, r.severity,
                       r.status, r.linked_task_id, r.created_at
                FROM evidence_regressions r
                JOIN evidence e ON r.evidence_id = e.id
                WHERE e.project_id = %s {status_filter}
                ORDER BY r.created_at DESC
                LIMIT %s
                """,
                params,
            )
            for row in cur.fetchall():
                created_at_val = row[9]
                created_at_str = created_at_val.isoformat() if created_at_val else ""
                formatted_regressions.append(
                    RegressionListItem(
                        id=row[0],
                        evidence_id=row[1],
                        baseline_evidence_id=row[2],
                        regression_type=row[3] or "unknown",
                        pixel_diff_pct=row[4],
                        console_errors_added=row[5] or 0,
                        severity=row[6] or "unknown",
                        status=row[7] or "detected",
                        linked_task_id=row[8],
                        created_at=created_at_str,
                    ).model_dump()
                )

    return {
        "regressions": formatted_regressions,
        "count": len(formatted_regressions),
    }


@router.post("/projects/{project_id}/evidence/regressions/{regression_id}/review")
async def review_regression(
    project_id: str,
    regression_id: int,
    request: RegressionReviewRequest,
) -> dict[str, Any]:
    """Review a detected regression.

    Verdicts:
    - accept_change: The change was intentional. Updates the baseline.
    - confirm_regression: The change is a bug. Optionally creates a task.
    """
    from ...storage import evidence_regressions
    from ...storage.connection import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.id, r.evidence_id, r.baseline_evidence_id, r.status
            FROM evidence_regressions r
            JOIN evidence e ON r.evidence_id = e.id
            WHERE r.id = %s AND e.project_id = %s
            """,
            (regression_id, project_id),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Regression not found")

    current_status = row[3]
    if current_status == "resolved":
        raise HTTPException(status_code=400, detail="Regression is already resolved")

    if request.verdict == "accept_change":
        evidence_regressions.update_status(
            regression_id,
            status="resolved",
            reviewed_by="user",
        )

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE evidence
                SET is_baseline = true
                WHERE id = %s
                """,
                (row[1],),
            )
            if row[2]:
                cur.execute(
                    """
                    UPDATE evidence
                    SET is_baseline = false
                    WHERE id = %s
                    """,
                    (row[2],),
                )
            conn.commit()

        return {
            "success": True,
            "verdict": "accept_change",
            "message": "Change accepted. New baseline set.",
        }

    elif request.verdict == "confirm_regression":
        evidence_regressions.update_status(
            regression_id,
            status="reviewed",
            reviewed_by="user",
        )

        from ...tasks.evidence_capture import create_regression_task

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT ee.path, r.regression_type, r.severity
                FROM evidence_regressions r
                JOIN evidence e ON r.evidence_id = e.id
                LEFT JOIN explorer_entries ee ON e.explorer_entry_id = ee.id
                WHERE r.id = %s
                """,
                (regression_id,),
            )
            info_row = cur.fetchone()

        if info_row:
            entry_path = info_row[0] or f"evidence-{row[1]}"
            regression_type = info_row[1] or "unknown"
            severity = info_row[2] or "medium"

            task = create_regression_task(
                project_id=project_id,
                regression_id=regression_id,
                entry_path=entry_path,
                regression_type=regression_type,
                severity=severity,
                evidence_id=row[1],
                baseline_evidence_id=row[2],
            )

            if task:
                return {
                    "success": True,
                    "verdict": "confirm_regression",
                    "message": "Regression confirmed. Bug task created.",
                    "task_id": task["id"],
                }

        return {
            "success": True,
            "verdict": "confirm_regression",
            "message": "Regression confirmed.",
        }

    else:
        raise HTTPException(
            status_code=400,
            detail="Invalid verdict. Use 'accept_change' or 'confirm_regression'.",
        )
