"""Evidence API - Evidence capture and retrieval for feature verification.

This module provides REST API endpoints for evidence:
- GET /projects/{project_id}/evidence/{feature_id}/{criterion_id} - Get evidence with optional version
- POST /projects/{project_id}/evidence/refresh - Capture new evidence
- POST /projects/{project_id}/evidence/{evidence_id}/review - Submit user review
- GET /projects/{project_id}/evidence/summary - Get evidence statistics
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..services.evidence_manager import (
    capture_evidence,
    get_evidence,
    get_evidence_base_dir,
    get_evidence_versions,
    get_next_version,
    get_summary,
    read_evidence_file,
    save_evidence,
    update_user_review,
)

router = APIRouter()


class RefreshRequest(BaseModel):
    """Request to capture new evidence."""

    feature_id: str
    criterion_id: str
    url: str


class ReviewRequest(BaseModel):
    """Request to submit user review."""

    approved: bool | None = None
    notes: str | None = None


@router.get("/projects/{project_id}/evidence/{feature_id}/{criterion_id}")
async def get_evidence_endpoint(
    project_id: str,
    feature_id: str,
    criterion_id: str,
    version: int | None = Query(None, description="Specific version (default: current)"),
    include_evidence: bool = Query(False, description="Include evidence.json data"),
) -> dict[str, Any]:
    """Get evidence metadata and optionally the evidence data."""
    evidence = get_evidence(project_id, feature_id, criterion_id, version)

    if not evidence:
        raise HTTPException(status_code=404, detail="No evidence captured yet")

    result: dict[str, Any] = {
        "artifact": {
            "id": evidence["id"],
            "artifactId": evidence["evidence_id"],
            "featureId": evidence["feature_id"],
            "criterionId": evidence["criterion_id"],
            "version": evidence["version"],
            "isCurrent": evidence["is_current"],
            "capturedAt": evidence["captured_at"],
            "expiresAt": evidence["expires_at"],
            "qualityStatus": evidence["quality_status"],
            "confidence": evidence["confidence"],
            "userApproved": evidence["user_approved"],
            "userNotes": evidence["user_notes"],
            "fileSizeBytes": evidence["file_size_bytes"],
        },
        "versions": [],
        "screenshotUrl": f"/api/projects/{project_id}/evidence/{feature_id}/{criterion_id}/screenshot?version={evidence['version']}",
        "evidenceUrl": f"/api/projects/{project_id}/evidence/{feature_id}/{criterion_id}/data?version={evidence['version']}",
    }

    # Get all versions
    versions = get_evidence_versions(project_id, feature_id, criterion_id)
    result["versions"] = [
        {
            "id": v["id"],
            "artifactId": v["evidence_id"],
            "featureId": v["feature_id"],
            "criterionId": v["criterion_id"],
            "version": v["version"],
            "isCurrent": v["is_current"],
            "capturedAt": v["captured_at"],
            "expiresAt": v["expires_at"],
            "qualityStatus": v["quality_status"],
            "confidence": v["confidence"],
            "userApproved": v["user_approved"],
            "userNotes": v["user_notes"],
            "fileSizeBytes": v["file_size_bytes"],
        }
        for v in versions
    ]

    # Include evidence data if requested
    if include_evidence:
        evidence_data = read_evidence_file(
            project_id, feature_id, criterion_id, evidence["version"]
        )
        result["evidence"] = evidence_data

    return result


@router.get("/projects/{project_id}/evidence/{feature_id}/{criterion_id}/screenshot")
async def get_screenshot(
    project_id: str,
    feature_id: str,
    criterion_id: str,
    version: int | None = Query(None, description="Specific version"),
) -> FileResponse:
    """Get the screenshot image for evidence."""
    evidence = get_evidence(project_id, feature_id, criterion_id, version)

    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")

    evidence_base = get_evidence_base_dir(project_id)
    screenshot_path = (
        evidence_base
        / feature_id
        / criterion_id
        / f"v{evidence['version']}"
        / "screenshot.png"
    )

    if not screenshot_path.exists():
        raise HTTPException(status_code=404, detail="Screenshot file not found")

    return FileResponse(
        path=screenshot_path,
        media_type="image/png",
        filename=f"{feature_id}-{criterion_id}-v{evidence['version']}.png",
    )


@router.get("/projects/{project_id}/evidence/{feature_id}/{criterion_id}/data")
async def get_evidence_data(
    project_id: str,
    feature_id: str,
    criterion_id: str,
    version: int | None = Query(None, description="Specific version"),
) -> dict[str, Any]:
    """Get the evidence.json data for evidence."""
    evidence = get_evidence(project_id, feature_id, criterion_id, version)

    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")

    evidence_data = read_evidence_file(
        project_id, feature_id, criterion_id, evidence["version"]
    )

    if not evidence_data:
        raise HTTPException(status_code=404, detail="Evidence data file not found")

    return evidence_data


@router.post("/projects/{project_id}/evidence/refresh")
async def refresh_evidence(
    project_id: str,
    request: RefreshRequest,
) -> dict[str, Any]:
    """Capture new evidence for a criterion."""
    # Get next version number
    next_version = get_next_version(
        project_id, request.feature_id, request.criterion_id
    )

    # Capture evidence
    result = await capture_evidence(
        project_id=project_id,
        url=request.url,
        feature_id=request.feature_id,
        criterion_id=request.criterion_id,
    )

    if not result.get("success"):
        return {
            "success": False,
            "error": result.get("error", "Capture failed"),
        }

    # Save to database
    evidence_base = get_evidence_base_dir(project_id)
    file_path = str(
        evidence_base
        / request.feature_id
        / request.criterion_id
        / f"v{result.get('version', next_version)}"
    )

    # Calculate file size
    file_size = 0
    path = Path(file_path)
    if path.exists():
        for f in path.iterdir():
            if f.is_file():
                file_size += f.stat().st_size

    save_evidence(
        project_id=project_id,
        feature_id=request.feature_id,
        criterion_id=request.criterion_id,
        version=result.get("version", next_version),
        file_path=file_path,
        file_size_bytes=file_size,
    )

    return {
        "success": True,
        "version": result.get("version", next_version),
        "message": f"Evidence captured (v{result.get('version', next_version)})",
    }


@router.post("/projects/{project_id}/evidence/{evidence_id}/review")
async def submit_review(
    project_id: str,
    evidence_id: str,
    request: ReviewRequest,
) -> dict[str, Any]:
    """Submit a user review for evidence."""
    success = update_user_review(
        project_id=project_id,
        evidence_id=evidence_id,
        approved=request.approved,
        notes=request.notes,
    )

    if not success:
        raise HTTPException(status_code=404, detail="Evidence not found")

    return {"success": True, "message": "Review submitted"}


@router.get("/projects/{project_id}/evidence/summary")
async def get_evidence_summary(project_id: str) -> dict[str, Any]:
    """Get evidence statistics for a project."""
    return get_summary(project_id)
