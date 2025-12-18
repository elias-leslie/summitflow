"""Evidence API - Evidence capture and retrieval for feature verification.

This module provides REST API endpoints for evidence:
- GET /projects/{project_id}/evidence/{feature_id}/{criterion_id} - Get evidence with optional version
- POST /projects/{project_id}/evidence/refresh - Capture new evidence (server-side)
- POST /projects/{project_id}/evidence/viewport-capture - Capture from client-side screenshot
- POST /projects/{project_id}/evidence/debug-capture - Quick debug capture (no DB entry)
- POST /projects/{project_id}/evidence/{evidence_id}/review - Submit user review
- GET /projects/{project_id}/evidence/summary - Get evidence statistics
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..logging_config import get_logger
from ..services.evidence_manager import (
    capture_evidence,
    get_evidence,
    get_evidence_base_dir,
    get_evidence_versions,
    get_next_version,
    get_summary,
    list_evidence,
    read_evidence_file,
    save_evidence,
    update_user_review,
)

logger = get_logger(__name__)

router = APIRouter()

# Debug captures directory (project-scoped)
DEBUG_CAPTURES_BASE = Path("/home/kasadis/summitflow/data/projects")


class RefreshRequest(BaseModel):
    """Request to capture new evidence."""

    feature_id: str
    criterion_id: str
    url: str


class ReviewRequest(BaseModel):
    """Request to submit user review."""

    approved: bool | None = None
    notes: str | None = None


class ClientEvidence(BaseModel):
    """Client-side evidence gathered before screenshot."""

    console: dict = Field(default_factory=dict, description="Console errors/warnings")
    network: dict = Field(default_factory=dict, description="Network failures")


class ViewportCaptureRequest(BaseModel):
    """Request to upload a client-side viewport capture."""

    feature_id: str = Field(..., description="Feature ID")
    criterion_id: str = Field(..., description="Criterion ID")
    screenshot_base64: str = Field(..., description="Base64-encoded PNG screenshot")
    url: str = Field(..., description="URL of the captured page")
    viewport_width: int = Field(..., description="Viewport width")
    viewport_height: int = Field(..., description="Viewport height")
    scroll_x: int = Field(0, description="Horizontal scroll position")
    scroll_y: int = Field(0, description="Vertical scroll position")
    page_title: str = Field("", description="Page title")
    client_evidence: ClientEvidence | None = Field(
        None, description="Client-side console/network evidence"
    )


class DebugCaptureRequest(BaseModel):
    """Request for debug viewport capture (no DB entry)."""

    screenshot_base64: str = Field(..., description="Base64-encoded PNG screenshot")
    url: str = Field(..., description="URL of the captured page")
    page_title: str = Field("", description="Page title")
    client_evidence: ClientEvidence | None = Field(
        None, description="Client-side console/network evidence"
    )


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


@router.get("/projects/{project_id}/evidence")
async def list_evidence_endpoint(
    project_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    feature_id: str | None = Query(None, description="Filter by feature ID"),
    status: str | None = Query(None, description="Filter by quality status"),
    search: str | None = Query(None, description="Search feature/criterion IDs"),
) -> dict[str, Any]:
    """List all evidence for a project with optional filtering."""
    evidence_list, total = list_evidence(
        project_id=project_id,
        limit=limit,
        offset=offset,
        feature_id=feature_id,
        quality_status=status,
        search=search,
    )

    return {
        "evidence": [
            {
                "id": e["id"],
                "evidenceId": e["evidence_id"],
                "featureId": e["feature_id"],
                "criterionId": e["criterion_id"],
                "version": e["version"],
                "isCurrent": e["is_current"],
                "capturedAt": e["captured_at"],
                "expiresAt": e["expires_at"],
                "qualityStatus": e["quality_status"],
                "confidence": e["confidence"],
                "userApproved": e["user_approved"],
                "userNotes": e["user_notes"],
                "fileSizeBytes": e["file_size_bytes"],
                "screenshotUrl": f"/summitflow/api/projects/{project_id}/evidence/{e['feature_id']}/{e['criterion_id']}/screenshot?version={e['version']}",
            }
            for e in evidence_list
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/projects/{project_id}/evidence/summary")
async def get_evidence_summary(project_id: str) -> dict[str, Any]:
    """Get evidence statistics for a project."""
    return get_summary(project_id)


# =========================================================================
# Client-Side Capture Endpoints
# =========================================================================


@router.post("/projects/{project_id}/evidence/viewport-capture")
async def viewport_capture(
    project_id: str,
    request: ViewportCaptureRequest,
) -> dict[str, Any]:
    """Upload a client-side viewport capture.

    This endpoint receives a screenshot captured directly from the user's browser
    using the Screen Capture API, preserving exact viewport state (scroll position,
    expanded sections, form values, etc.).
    """
    try:
        # Decode base64 screenshot
        try:
            screenshot_data = base64.b64decode(request.screenshot_base64)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid base64 screenshot data")

        # Get next version and create output directory
        version = get_next_version(project_id, request.feature_id, request.criterion_id)
        evidence_base = get_evidence_base_dir(project_id)
        output_dir = (
            evidence_base / request.feature_id / request.criterion_id / f"v{version}"
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save screenshot
        screenshot_path = output_dir / "screenshot.png"
        screenshot_path.write_bytes(screenshot_data)

        # Create evidence.json with viewport metadata
        evidence_data = {
            "metadata": {
                "url": request.url,
                "featureId": request.feature_id,
                "criterionId": request.criterion_id,
                "projectId": project_id,
                "version": version,
                "capturedAt": datetime.now(UTC).isoformat(),
                "pageTitle": request.page_title,
                "viewport": {
                    "width": request.viewport_width,
                    "height": request.viewport_height,
                },
                "scroll": {
                    "x": request.scroll_x,
                    "y": request.scroll_y,
                },
                "captureMethod": "client-side-screen-capture-api",
            },
            "console": {
                "errorCount": (
                    request.client_evidence.console.get("errorCount", 0)
                    if request.client_evidence
                    else 0
                ),
                "warningCount": (
                    request.client_evidence.console.get("warningCount", 0)
                    if request.client_evidence
                    else 0
                ),
                "errors": (
                    request.client_evidence.console.get("errors", [])
                    if request.client_evidence
                    else []
                ),
                "warnings": (
                    request.client_evidence.console.get("warnings", [])
                    if request.client_evidence
                    else []
                ),
                "note": "Client-side evidence from visible error elements",
            },
            "network": {
                "totalRequests": 0,
                "failedRequests": (
                    request.client_evidence.network.get("failureCount", 0)
                    if request.client_evidence
                    else 0
                ),
                "failures": (
                    request.client_evidence.network.get("failures", [])
                    if request.client_evidence
                    else []
                ),
                "slowRequests": [],
                "note": "Client-side evidence from Performance API",
            },
            "pageState": {
                "hasContent": True,
                "visibleTextSample": "",
                "keyElements": {},
                "note": "Captured user's exact viewport state",
            },
        }

        evidence_path = output_dir / "evidence.json"
        evidence_path.write_text(json.dumps(evidence_data, indent=2))

        # Update current symlink
        current_link = evidence_base / request.feature_id / request.criterion_id / "current"
        if current_link.is_symlink():
            current_link.unlink()
        current_link.symlink_to(f"v{version}")

        # Save to database
        file_size = len(screenshot_data) + len(json.dumps(evidence_data))
        save_evidence(
            project_id=project_id,
            feature_id=request.feature_id,
            criterion_id=request.criterion_id,
            version=version,
            file_path=str(output_dir),
            file_size_bytes=file_size,
        )

        logger.info(
            "viewport_capture_saved",
            project_id=project_id,
            feature_id=request.feature_id,
            criterion_id=request.criterion_id,
            version=version,
            scroll_y=request.scroll_y,
        )

        return {
            "success": True,
            "version": version,
            "feature_id": request.feature_id,
            "criterion_id": request.criterion_id,
            "evidence": evidence_data,
            "files": [
                {"name": "screenshot.png", "size": len(screenshot_data)},
                {"name": "evidence.json", "size": len(json.dumps(evidence_data))},
            ],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("viewport_capture_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.post("/projects/{project_id}/evidence/debug-capture")
async def debug_capture(
    project_id: str,
    request: DebugCaptureRequest,
) -> dict[str, Any]:
    """Save a debug viewport capture without creating a feature entry.

    Saves to: data/projects/{project_id}/debug-captures/{timestamp}.png
    Also maintains: latest.png (symlink to most recent)

    This is for quick debugging - Claude can easily find via:
    - Read /home/kasadis/summitflow/data/projects/{project_id}/debug-captures/latest.png
    - ls -lt data/projects/{project_id}/debug-captures/ | head
    """
    try:
        # Decode base64 screenshot
        try:
            screenshot_data = base64.b64decode(request.screenshot_base64)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid base64 screenshot data")

        # Ensure directory exists
        debug_dir = DEBUG_CAPTURES_BASE / project_id / "debug-captures"
        debug_dir.mkdir(parents=True, exist_ok=True)

        # Create timestamped filename
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        screenshot_filename = f"{timestamp}.png"
        screenshot_path = debug_dir / screenshot_filename

        # Save screenshot
        screenshot_path.write_bytes(screenshot_data)

        # Save evidence.json alongside screenshot
        evidence_filename = f"{timestamp}.json"
        evidence_path = debug_dir / evidence_filename
        evidence_data = {
            "metadata": {
                "url": request.url,
                "pageTitle": request.page_title,
                "projectId": project_id,
                "capturedAt": datetime.now(UTC).isoformat(),
                "captureMethod": "client-side-screen-capture-api",
            },
            "console": {
                "errorCount": (
                    request.client_evidence.console.get("errorCount", 0)
                    if request.client_evidence
                    else 0
                ),
                "warningCount": (
                    request.client_evidence.console.get("warningCount", 0)
                    if request.client_evidence
                    else 0
                ),
                "errors": (
                    request.client_evidence.console.get("errors", [])
                    if request.client_evidence
                    else []
                ),
                "warnings": (
                    request.client_evidence.console.get("warnings", [])
                    if request.client_evidence
                    else []
                ),
            },
            "network": {
                "failedRequests": (
                    request.client_evidence.network.get("failureCount", 0)
                    if request.client_evidence
                    else 0
                ),
                "failures": (
                    request.client_evidence.network.get("failures", [])
                    if request.client_evidence
                    else []
                ),
            },
        }
        evidence_path.write_text(json.dumps(evidence_data, indent=2))

        # Update latest.png symlink
        latest_link = debug_dir / "latest.png"
        if latest_link.is_symlink() or latest_link.exists():
            latest_link.unlink()
        latest_link.symlink_to(screenshot_filename)

        # Update latest.json symlink
        latest_json_link = debug_dir / "latest.json"
        if latest_json_link.is_symlink() or latest_json_link.exists():
            latest_json_link.unlink()
        latest_json_link.symlink_to(evidence_filename)

        # Clean up old captures (keep last 20 pairs)
        all_captures = sorted(debug_dir.glob("*.png"))
        all_captures = [p for p in all_captures if p.name not in ("latest.png",)]
        if len(all_captures) > 20:
            for old_capture in all_captures[:-20]:
                old_capture.unlink()
                # Also remove matching .json
                old_json = old_capture.with_suffix(".json")
                if old_json.exists():
                    old_json.unlink()

        logger.info(
            "debug_capture_saved",
            project_id=project_id,
            filename=screenshot_filename,
            url=request.url,
            size_kb=len(screenshot_data) // 1024,
        )

        return {
            "success": True,
            "filename": screenshot_filename,
            "evidence_filename": evidence_filename,
            "path": str(screenshot_path),
            "evidence_path": str(evidence_path),
            "latest_path": str(latest_link),
            "latest_json_path": str(latest_json_link),
            "url": request.url,
            "size_bytes": len(screenshot_data),
            "evidence": evidence_data,
            "message": f"Saved to {screenshot_path}. Claude: Read data/projects/{project_id}/debug-captures/latest.png",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("debug_capture_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/projects/{project_id}/evidence/debug-captures")
async def list_debug_captures(
    project_id: str,
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    """List recent debug captures for a project.

    Useful for Claude to see what captures are available.
    """
    try:
        debug_dir = DEBUG_CAPTURES_BASE / project_id / "debug-captures"
        if not debug_dir.exists():
            return {"captures": [], "count": 0, "latest": None}

        # Get all PNG files except latest.png
        captures = []
        for path in sorted(debug_dir.glob("*.png"), reverse=True):
            if path.name == "latest.png":
                continue
            captures.append(
                {
                    "filename": path.name,
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                    "created_at": datetime.fromtimestamp(
                        path.stat().st_mtime, tz=UTC
                    ).isoformat(),
                }
            )
            if len(captures) >= limit:
                break

        # Check latest symlink
        latest_link = debug_dir / "latest.png"
        latest_target = None
        if latest_link.is_symlink():
            latest_target = latest_link.resolve().name

        return {
            "captures": captures,
            "count": len(captures),
            "latest": latest_target,
            "latest_path": str(debug_dir / "latest.png"),
        }

    except Exception as e:
        logger.error("list_debug_captures_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from None
