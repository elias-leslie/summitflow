"""Server-side evidence capture endpoints.

Explorer-driven capture orchestration via Celery tasks.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


class CaptureRequest(BaseModel):
    """Request to trigger evidence capture."""

    scope: str = Field(
        "project",
        description="Capture scope: 'project' (all entries), 'entry' (specific entries)",
    )
    entry_ids: list[int] | None = Field(None, description="Entry IDs when scope='entry'")
    environment: str = Field("local", description="Environment: local, staging, production")


class CaptureJobStatus(BaseModel):
    """Status of a capture job."""

    job_id: int
    status: str
    scope: str
    entries_captured: int
    regressions_found: int
    started_at: str | None
    completed_at: str | None
    errors: list[str]


@router.post("/projects/{project_id}/evidence/capture")
async def trigger_capture(
    project_id: str,
    request: CaptureRequest,
) -> dict[str, Any]:
    """Trigger evidence capture for explorer entries.

    Captures screenshots for pages and API responses for endpoints.
    Returns a job_id for status polling.
    """
    from ...tasks.evidence_capture import daily_evidence_capture

    try:
        result = daily_evidence_capture.apply_async(
            kwargs={
                "project_id": project_id,
                "scope": request.scope,
                "entry_ids": request.entry_ids,
                "environment": request.environment,
            }
        )

        if request.scope == "entry" and request.entry_ids and len(request.entry_ids) <= 3:
            sync_result = daily_evidence_capture(
                project_id=project_id,
                scope=request.scope,
                entry_ids=request.entry_ids,
                environment=request.environment,
            )
            return {
                "success": True,
                "job_id": sync_result.get("job_id"),
                "status": "completed",
                "captured": sync_result.get("captured", 0),
                "regressions_found": sync_result.get("regressions_found", 0),
            }

        return {
            "success": True,
            "task_id": result.id,
            "message": "Capture job queued. Poll /evidence/capture/status/{job_id} for progress.",
        }

    except Exception as e:
        logger.error("trigger_capture_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/projects/{project_id}/evidence/capture/status/{job_id}")
async def get_capture_status(
    project_id: str,
    job_id: int,
) -> CaptureJobStatus:
    """Get status of a capture job."""
    from ...storage.connection import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status, scope, entries_captured, regressions_found,
                   started_at, completed_at, error_message
            FROM evidence_capture_jobs
            WHERE id = %s AND project_id = %s
            """,
            (job_id, project_id),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Capture job not found")

    return CaptureJobStatus(
        job_id=row[0],
        status=row[1],
        scope=row[2],
        entries_captured=row[3] or 0,
        regressions_found=row[4] or 0,
        started_at=row[5].isoformat() if row[5] else None,
        completed_at=row[6].isoformat() if row[6] else None,
        errors=row[7].split("\n") if row[7] else [],
    )
