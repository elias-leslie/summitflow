"""Core evidence retrieval endpoints.

Basic CRUD operations for evidence - get, list, summary.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ...logging_config import get_logger
from ...services.evidence_manager import (
    get_evidence,
    get_evidence_base_dir,
    get_evidence_versions,
    get_summary,
    list_evidence,
    read_evidence_file,
)

logger = get_logger(__name__)

router = APIRouter()


def _format_evidence_record(e: dict[str, Any], *, project_id: str | None = None) -> dict[str, Any]:
    """Convert snake_case evidence record to camelCase for API response.

    Args:
        e: Evidence record from database
        project_id: If provided, includes screenshotUrl in response
    """
    result = {
        "id": e["id"],
        "evidenceId": e.get("evidence_id"),
        "artifactId": e.get("evidence_id"),
        "capabilityId": e["capability_id"],
        "criterionId": e["criterion_id"],
        "version": e["version"],
        "isCurrent": e["is_current"],
        "capturedAt": e["captured_at"],
        "qualityStatus": e["quality_status"],
        "confidence": e["confidence"],
        "userApproved": e["user_approved"],
        "userNotes": e["user_notes"],
        "fileSizeBytes": e["file_size_bytes"],
        "criterionDbId": e.get("criterion_db_id"),
        "testRunId": e.get("test_run_id"),
        "autoCaptured": e.get("auto_captured", False),
        "criterionText": e.get("criterion_text"),
    }
    if project_id:
        result["screenshotUrl"] = (
            f"/api/projects/{project_id}/evidence/{e['capability_id']}"
            f"/{e['criterion_id']}/screenshot?version={e['version']}"
        )
    return result


@router.get("/projects/{project_id}/evidence/{capability_id}/{criterion_id}")
async def get_evidence_endpoint(
    project_id: str,
    capability_id: str,
    criterion_id: str,
    version: int | None = Query(None, description="Specific version (default: current)"),
    include_evidence: bool = Query(False, description="Include evidence.json data"),
) -> dict[str, Any]:
    """Get evidence metadata and optionally the evidence data."""
    evidence = get_evidence(project_id, capability_id, criterion_id, version)

    if not evidence:
        raise HTTPException(status_code=404, detail="No evidence captured yet")

    result: dict[str, Any] = {
        "artifact": _format_evidence_record(evidence),
        "versions": [],
        "screenshotUrl": f"/api/projects/{project_id}/evidence/{capability_id}/{criterion_id}/screenshot?version={evidence['version']}",
        "evidenceUrl": f"/api/projects/{project_id}/evidence/{capability_id}/{criterion_id}/data?version={evidence['version']}",
    }

    versions = get_evidence_versions(project_id, capability_id, criterion_id)
    result["versions"] = [_format_evidence_record(v) for v in versions]

    if include_evidence:
        evidence_data = read_evidence_file(
            project_id, capability_id, criterion_id, evidence["version"]
        )
        result["evidence"] = evidence_data

    return result


@router.get("/projects/{project_id}/evidence/{capability_id}/{criterion_id}/screenshot")
async def get_screenshot(
    project_id: str,
    capability_id: str,
    criterion_id: str,
    version: int | None = Query(None, description="Specific version"),
) -> FileResponse:
    """Get the screenshot image for evidence."""
    evidence = get_evidence(project_id, capability_id, criterion_id, version)

    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")

    evidence_base = get_evidence_base_dir(project_id)
    screenshot_path = (
        evidence_base / capability_id / criterion_id / f"v{evidence['version']}" / "screenshot.png"
    )

    if not screenshot_path.exists():
        raise HTTPException(status_code=404, detail="Screenshot file not found")

    return FileResponse(
        path=screenshot_path,
        media_type="image/png",
        filename=f"{capability_id}-{criterion_id}-v{evidence['version']}.png",
    )


@router.get("/projects/{project_id}/evidence/{capability_id}/{criterion_id}/data")
async def get_evidence_data(
    project_id: str,
    capability_id: str,
    criterion_id: str,
    version: int | None = Query(None, description="Specific version"),
) -> dict[str, Any]:
    """Get the evidence.json data for evidence."""
    evidence = get_evidence(project_id, capability_id, criterion_id, version)

    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")

    evidence_data = read_evidence_file(project_id, capability_id, criterion_id, evidence["version"])

    if not evidence_data:
        raise HTTPException(status_code=404, detail="Evidence data file not found")

    return evidence_data


@router.get("/projects/{project_id}/evidence")
async def list_evidence_endpoint(
    project_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    capability_id: str | None = Query(None, description="Filter by capability ID"),
    status: str | None = Query(None, description="Filter by quality status"),
    search: str | None = Query(None, description="Search capability/criterion IDs"),
    entry_id: int | None = Query(None, description="Filter by explorer entry ID"),
) -> dict[str, Any]:
    """List all evidence for a project with optional filtering."""
    evidence_list, total = list_evidence(
        project_id=project_id,
        limit=limit,
        offset=offset,
        capability_id=capability_id,
        quality_status=status,
        search=search,
        explorer_entry_id=entry_id,
    )

    return {
        "evidence": [_format_evidence_record(e, project_id=project_id) for e in evidence_list],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/projects/{project_id}/evidence/summary")
async def get_evidence_summary(project_id: str) -> dict[str, Any]:
    """Get evidence statistics for a project."""
    return get_summary(project_id)


@router.get("/projects/{project_id}/evidence/by-id/{evidence_id}")
async def get_evidence_by_id(project_id: str, evidence_id: int) -> dict[str, Any]:
    """Get a single evidence record by its database ID."""
    from ...storage.connection import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, evidence_id, capability_id, criterion_id,
                   version, is_current, captured_at, quality_status, confidence,
                   user_approved, user_notes, file_size_bytes, metadata
            FROM evidence
            WHERE id = %s AND project_id = %s
            """,
            (evidence_id, project_id),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Evidence not found")

    captured_at = row[7]
    captured_at_str = captured_at.isoformat() if captured_at else None

    return {
        "id": row[0],
        "project_id": row[1],
        "evidence_id": row[2],
        "capability_id": row[3],
        "criterion_id": row[4],
        "version": row[5],
        "is_current": row[6],
        "captured_at": captured_at_str,
        "quality_status": row[8],
        "confidence": row[9],
        "user_approved": row[10],
        "user_notes": row[11],
        "file_size_bytes": row[12],
        "metadata": row[13] or {},
    }
