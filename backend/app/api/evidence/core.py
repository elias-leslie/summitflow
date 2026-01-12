"""Core evidence retrieval endpoints.

Basic CRUD operations for evidence - get, list, summary.

Evidence is now linked to task_id and/or explorer_entry_id.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ...logging_config import get_logger
from ...services.evidence_manager import (
    EVIDENCE_TYPES,
    get_evidence_by_id,
    get_evidence_for_entry,
    get_evidence_for_task,
    get_evidence_path,
    get_summary,
    list_evidence,
    read_evidence_file,
)

logger = get_logger(__name__)

router = APIRouter()


def _format_evidence_record(e: dict[str, Any], *, project_id: str | None = None) -> dict[str, Any]:
    """Convert snake_case evidence record to camelCase for API response."""
    result = {
        "id": e["id"],
        "evidenceId": e.get("evidence_id"),
        "taskId": e.get("task_id"),
        "explorerEntryId": e.get("explorer_entry_id"),
        "evidenceType": e.get("evidence_type"),
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
        "linkedEvidenceId": e.get("linked_evidence_id"),
        "mockupStatus": e.get("mockup_status"),
        "environment": e.get("environment"),
        "viewportName": e.get("viewport_name"),
    }
    if project_id and e.get("evidence_id"):
        result["screenshotUrl"] = (
            f"/api/projects/{project_id}/evidence/{e['evidence_id']}/screenshot"
        )
    return result


# Static routes must be defined before dynamic {evidence_id} routes
@router.get("/projects/{project_id}/evidence/summary")
async def get_evidence_summary(project_id: str) -> dict[str, Any]:
    """Get evidence statistics for a project."""
    return get_summary(project_id)


@router.get("/projects/{project_id}/evidence/types")
async def get_evidence_types() -> dict[str, Any]:
    """Get valid evidence types."""
    return {"types": list(EVIDENCE_TYPES)}


@router.get("/projects/{project_id}/evidence/{evidence_id}")
async def get_evidence_endpoint(
    project_id: str,
    evidence_id: str,
    include_data: bool = Query(False, description="Include evidence.json data"),
) -> dict[str, Any]:
    """Get evidence metadata by evidence_id."""
    evidence = get_evidence_by_id(project_id, evidence_id)

    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")

    result: dict[str, Any] = {
        "evidence": _format_evidence_record(evidence, project_id=project_id),
        "screenshotUrl": f"/api/projects/{project_id}/evidence/{evidence_id}/screenshot",
        "dataUrl": f"/api/projects/{project_id}/evidence/{evidence_id}/data",
    }

    if include_data:
        evidence_data = read_evidence_file(project_id, evidence_id, evidence.get("version"))
        result["data"] = evidence_data

    return result


@router.get("/projects/{project_id}/evidence/{evidence_id}/screenshot")
async def get_screenshot(
    project_id: str,
    evidence_id: str,
) -> FileResponse:
    """Get the screenshot image for evidence."""
    evidence = get_evidence_by_id(project_id, evidence_id)

    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")

    version = evidence.get("version", 1)
    evidence_dir = get_evidence_path(project_id, evidence_id, version)
    screenshot_path = evidence_dir / "screenshot.png"

    if not screenshot_path.exists():
        raise HTTPException(status_code=404, detail="Screenshot file not found")

    return FileResponse(
        path=screenshot_path,
        media_type="image/png",
        filename=f"{evidence_id}-v{version}.png",
    )


@router.get("/projects/{project_id}/evidence/{evidence_id}/data")
async def get_evidence_data(
    project_id: str,
    evidence_id: str,
) -> dict[str, Any]:
    """Get the evidence.json data."""
    evidence = get_evidence_by_id(project_id, evidence_id)

    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")

    evidence_data = read_evidence_file(project_id, evidence_id, evidence.get("version"))

    if not evidence_data:
        raise HTTPException(status_code=404, detail="Evidence data file not found")

    return evidence_data


@router.get("/projects/{project_id}/evidence")
async def list_evidence_endpoint(
    project_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    task_id: str | None = Query(None, description="Filter by task ID"),
    entry_id: int | None = Query(None, description="Filter by explorer entry ID"),
    evidence_type: str | None = Query(None, description="Filter by evidence type"),
    status: str | None = Query(None, description="Filter by quality status"),
    search: str | None = Query(None, description="Search evidence/task IDs"),
) -> dict[str, Any]:
    """List all evidence for a project with optional filtering."""
    if evidence_type and evidence_type not in EVIDENCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid evidence_type. Must be one of: {', '.join(EVIDENCE_TYPES)}",
        )

    evidence_list, total = list_evidence(
        project_id=project_id,
        limit=limit,
        offset=offset,
        task_id=task_id,
        explorer_entry_id=entry_id,
        evidence_type=evidence_type,
        quality_status=status,
        search=search,
    )

    return {
        "evidence": [_format_evidence_record(e, project_id=project_id) for e in evidence_list],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/projects/{project_id}/tasks/{task_id}/evidence")
async def get_task_evidence(
    project_id: str,
    task_id: str,
    evidence_type: str | None = Query(None, description="Filter by evidence type"),
) -> dict[str, Any]:
    """Get all evidence for a task."""
    evidence_list = get_evidence_for_task(
        project_id=project_id,
        task_id=task_id,
        evidence_type=evidence_type,
    )

    return {
        "evidence": [_format_evidence_record(e, project_id=project_id) for e in evidence_list],
        "total": len(evidence_list),
    }


@router.get("/projects/{project_id}/explorer/{entry_id}/evidence")
async def get_entry_evidence(
    project_id: str,
    entry_id: int,
    evidence_type: str | None = Query(None, description="Filter by evidence type"),
) -> dict[str, Any]:
    """Get all evidence for an explorer entry."""
    evidence_list = get_evidence_for_entry(
        project_id=project_id,
        explorer_entry_id=entry_id,
        evidence_type=evidence_type,
    )

    return {
        "evidence": [_format_evidence_record(e, project_id=project_id) for e in evidence_list],
        "total": len(evidence_list),
    }


# ============================================================
# Mockup-specific endpoints
# ============================================================


@router.get("/projects/{project_id}/explorer/{entry_id}/mockups")
async def get_entry_mockups(
    project_id: str,
    entry_id: int,
    status: str | None = Query(None, description="Filter by mockup status"),
) -> dict[str, Any]:
    """Get all mockups for an explorer entry.

    Optionally filter by mockup_status (generated, pending_approval, approved, rejected).
    """
    from ...services.evidence_manager import MOCKUP_STATUSES, get_mockups_for_entry

    if status and status not in MOCKUP_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(MOCKUP_STATUSES)}",
        )

    mockups = get_mockups_for_entry(project_id, entry_id, status=status)

    return {
        "mockups": [_format_evidence_record(m, project_id=project_id) for m in mockups],
        "total": len(mockups),
    }


@router.get("/projects/{project_id}/explorer/{entry_id}/mockups/comparison")
async def get_mockup_comparison(
    project_id: str,
    entry_id: int,
) -> dict[str, Any]:
    """Get approved mockup paired with latest screenshot for comparison.

    Returns the approved mockup (target state) and the linked screenshot (actual state)
    for side-by-side comparison in the UI.
    """
    from ...services.evidence_manager import get_approved_mockup, get_evidence_by_db_id

    approved_mockup = get_approved_mockup(project_id, entry_id)

    if not approved_mockup:
        raise HTTPException(
            status_code=404,
            detail="No approved mockup found for this entry",
        )

    linked_id = approved_mockup.get("linked_evidence_id")
    linked_screenshot = None
    if linked_id:
        linked_screenshot = get_evidence_by_db_id(linked_id)

    return {
        "mockup": _format_evidence_record(approved_mockup, project_id=project_id),
        "actualScreenshot": (
            _format_evidence_record(linked_screenshot, project_id=project_id)
            if linked_screenshot
            else None
        ),
    }


@router.patch("/projects/{project_id}/evidence/{evidence_id}/mockup-status")
async def update_evidence_mockup_status(
    project_id: str,
    evidence_id: str,
    status: str = Query(..., description="New mockup status"),
) -> dict[str, Any]:
    """Update the mockup_status of an evidence record.

    Valid statuses: generated, pending_approval, approved, rejected.
    """
    from ...services.evidence_manager import MOCKUP_STATUSES, update_mockup_status

    if status not in MOCKUP_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(MOCKUP_STATUSES)}",
        )

    success = update_mockup_status(project_id, evidence_id, status)

    if not success:
        raise HTTPException(
            status_code=404,
            detail="Evidence not found or not a mockup",
        )

    return {"success": True, "evidenceId": evidence_id, "mockupStatus": status}
