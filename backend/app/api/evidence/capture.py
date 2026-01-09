"""Server-side evidence capture endpoints.

Explorer-driven capture orchestration via Celery tasks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# Note: daily_evidence_capture is a Celery task with dynamic attributes (.apply_async, .delay)
# Type checker may not recognize these - they work at runtime
from ...logging_config import get_logger
from ...services.evidence_manager import (
    capture_evidence,
    get_evidence_base_dir,
    get_next_version,
    save_evidence,
)

logger = get_logger(__name__)

router = APIRouter()


class RefreshRequest(BaseModel):
    """Request to capture new evidence."""

    capability_id: str
    criterion_id: str
    url: str


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


@router.post("/projects/{project_id}/evidence/refresh")
async def refresh_evidence(
    project_id: str,
    request: RefreshRequest,
) -> dict[str, Any]:
    """Capture new evidence for a criterion.

    DEPRECATED: Evidence now auto-captures on test pass. Use POST /capabilities/{id}/verify
    to run tests and auto-capture evidence for linked criteria with verification_url.
    """
    logger.warning(
        "deprecated_endpoint_called",
        endpoint="/evidence/refresh",
        project_id=project_id,
        capability_id=request.capability_id,
    )
    next_version = get_next_version(project_id, request.capability_id, request.criterion_id)

    result = await capture_evidence(
        project_id=project_id,
        url=request.url,
        capability_id=request.capability_id,
        criterion_id=request.criterion_id,
    )

    if not result.get("success"):
        return {
            "success": False,
            "error": result.get("error", "Capture failed"),
        }

    evidence_base = get_evidence_base_dir(project_id)
    file_path = str(
        evidence_base
        / request.capability_id
        / request.criterion_id
        / f"v{result.get('version', next_version)}"
    )

    file_size = 0
    path = Path(file_path)
    if path.exists():
        for f in path.iterdir():
            if f.is_file():
                file_size += f.stat().st_size

    save_evidence(
        project_id=project_id,
        capability_id=request.capability_id,
        criterion_id=request.criterion_id,
        version=result.get("version", next_version),
        file_path=file_path,
        file_size_bytes=file_size,
    )

    return {
        "success": True,
        "version": result.get("version", next_version),
        "message": f"Evidence captured (v{result.get('version', next_version)})",
        "warning": "Deprecated: evidence auto-captures on test pass. Use POST /capabilities/{id}/verify",
    }


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
