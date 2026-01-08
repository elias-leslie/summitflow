"""Evidence API - Evidence capture and retrieval for capability verification.

This module provides REST API endpoints for evidence:
- GET /projects/{project_id}/evidence/{capability_id}/{criterion_id} - Get evidence with optional version
- POST /projects/{project_id}/evidence/refresh - Capture new evidence (server-side)
- POST /projects/{project_id}/evidence/viewport-capture - Capture from client-side screenshot
- POST /projects/{project_id}/evidence/debug-capture - Quick debug capture (no DB entry)
- POST /projects/{project_id}/evidence/{evidence_id}/review - Submit user review
- GET /projects/{project_id}/evidence/summary - Get evidence statistics
"""

from __future__ import annotations

import base64
import contextlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..logging_config import get_logger
from ..services.agents import AgentType, get_agent
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
    update_ai_review,
    update_user_review,
)

logger = get_logger(__name__)


def _format_evidence_record(e: dict[str, Any], *, project_id: str | None = None) -> dict[str, Any]:
    """Convert snake_case evidence record to camelCase for API response.

    Args:
        e: Evidence record from database
        project_id: If provided, includes screenshotUrl in response
    """
    result = {
        "id": e["id"],
        "evidenceId": e.get("evidence_id"),
        "artifactId": e.get("evidence_id"),  # Alias for legacy compatibility
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
        # New fields for criteria linkage
        "criterionDbId": e.get("criterion_db_id"),
        "testRunId": e.get("test_run_id"),
        "autoCaptured": e.get("auto_captured", False),
        # Criterion text from LEFT JOIN (shows what this evidence verifies)
        "criterionText": e.get("criterion_text"),
    }
    if project_id:
        result["screenshotUrl"] = (
            f"/api/projects/{project_id}/evidence/{e['capability_id']}"
            f"/{e['criterion_id']}/screenshot?version={e['version']}"
        )
    return result


router = APIRouter()

# Debug captures directory (project-scoped)
DEBUG_CAPTURES_BASE = Path("/home/kasadis/summitflow/data/projects")


class RefreshRequest(BaseModel):
    """Request to capture new evidence."""

    capability_id: str
    criterion_id: str
    url: str


class ReviewRequest(BaseModel):
    """Request to submit user review."""

    approved: bool | None = None
    notes: str | None = None


class AgentReviewRequest(BaseModel):
    """Request for agent to review evidence."""

    agent: str = Field(default="gemini", description="Agent type: 'claude' or 'gemini'")
    focus: str | None = Field(
        None,
        description="Optional focus area for analysis (e.g., 'accessibility', 'performance')",
    )


class ClientEvidence(BaseModel):
    """Client-side evidence gathered before screenshot."""

    console: dict[str, Any] = Field(default_factory=dict, description="Console errors/warnings")
    network: dict[str, Any] = Field(default_factory=dict, description="Network failures")


class ViewportCaptureRequest(BaseModel):
    """Request to upload a client-side viewport capture."""

    capability_id: str = Field(..., description="Capability ID")
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


def _extract_client_evidence(client_evidence: ClientEvidence | None) -> dict[str, Any]:
    """Extract normalized client evidence dict from ClientEvidence model.

    Returns console and network evidence with defaults if not provided.
    """
    if not client_evidence:
        return {
            "console": {
                "errorCount": 0,
                "warningCount": 0,
                "errors": [],
                "warnings": [],
            },
            "network": {
                "failureCount": 0,
                "failures": [],
            },
        }

    return {
        "console": {
            "errorCount": client_evidence.console.get("errorCount", 0),
            "warningCount": client_evidence.console.get("warningCount", 0),
            "errors": client_evidence.console.get("errors", []),
            "warnings": client_evidence.console.get("warnings", []),
        },
        "network": {
            "failureCount": client_evidence.network.get("failureCount", 0),
            "failures": client_evidence.network.get("failures", []),
        },
    }


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

    # Get all versions
    versions = get_evidence_versions(project_id, capability_id, criterion_id)
    result["versions"] = [_format_evidence_record(v) for v in versions]

    # Include evidence data if requested
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
    # Get next version number
    next_version = get_next_version(project_id, request.capability_id, request.criterion_id)

    # Capture evidence
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

    # Save to database
    evidence_base = get_evidence_base_dir(project_id)
    file_path = str(
        evidence_base
        / request.capability_id
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


@router.post("/projects/{project_id}/evidence/{evidence_id}/agent-review")
async def agent_review(
    project_id: str,
    evidence_id: str,
    request: AgentReviewRequest,
) -> dict[str, Any]:
    """Request an AI agent to analyze evidence and propose issues/features.

    The agent analyzes:
    - Screenshot content (described)
    - Console errors and warnings
    - Network failures
    - Page state (element counts, loading indicators)
    - Performance metrics

    Returns proposed issues with suggested features/fixes.
    """
    # Parse evidence_id to get capability_id, criterion_id, version
    # Format: {capability_id}-{criterion_id}-v{version} or direct DB lookup
    parts = evidence_id.rsplit("-v", 1)
    if len(parts) == 2:
        prefix = parts[0]
        version = int(parts[1]) if parts[1].isdigit() else None
        # Split prefix into capability_id and criterion_id
        prefix_parts = prefix.split("-")
        if len(prefix_parts) >= 2:
            capability_id = prefix_parts[0]
            criterion_id = "-".join(prefix_parts[1:])
        else:
            raise HTTPException(status_code=400, detail="Invalid evidence_id format")
    else:
        raise HTTPException(
            status_code=400,
            detail="Invalid evidence_id format. Expected: CAP-XXX-ac-XXX-vN",
        )

    # Get evidence data
    evidence_data = read_evidence_file(project_id, capability_id, criterion_id, version)
    if not evidence_data:
        raise HTTPException(status_code=404, detail="Evidence data not found")

    # Get agent
    try:
        if request.agent not in ("claude", "gemini"):
            raise HTTPException(status_code=400, detail="Agent must be 'claude' or 'gemini'")
        agent_type: AgentType = "claude" if request.agent == "claude" else "gemini"
        agent = get_agent(agent_type)
        if not agent.is_available():
            raise HTTPException(
                status_code=503,
                detail=f"{request.agent} agent is not available. Check CLI installation.",
            )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from None

    # Build analysis prompt
    console_summary = evidence_data.get("console", {})
    network_summary = evidence_data.get("network", {})
    page_state = evidence_data.get("pageState", {})
    performance = evidence_data.get("performance", {})
    metadata = evidence_data.get("metadata", {})

    prompt = f"""Analyze this UI evidence capture and identify issues.

## Page Information
- URL: {metadata.get("url", "Unknown")}
- Title: {metadata.get("pageTitle", "Unknown")}
- Captured: {metadata.get("capturedAt", "Unknown")}
- Viewport: {metadata.get("viewport", {})}

## Console Analysis
- Errors: {console_summary.get("errorCount", 0)}
- Warnings: {console_summary.get("warningCount", 0)}

Error Details:
{json.dumps(console_summary.get("errors", [])[:5], indent=2)}

Warning Details:
{json.dumps(console_summary.get("warnings", [])[:3], indent=2)}

## Network Analysis
- Total Requests: {network_summary.get("totalRequests", 0)}
- Failed Requests: {network_summary.get("failedRequests", 0)}

Failed Request Details:
{json.dumps(network_summary.get("failures", [])[:5], indent=2)}

Slow Requests (>3s):
{json.dumps(network_summary.get("slowRequests", [])[:3], indent=2)}

## Page State
- Has Content: {page_state.get("hasContent", False)}
- Key Elements: {json.dumps(page_state.get("keyElements", {}), indent=2)}
- Visible Text Sample: {page_state.get("visibleTextSample", "")[:200]}

## Performance
- Page Load: {performance.get("pageLoadMs", "N/A")} ms
- DOM Ready: {performance.get("domContentLoadedMs", "N/A")} ms
- LCP: {performance.get("largestContentfulPaintMs", "N/A")} ms

{f"Focus Area: {request.focus}" if request.focus else ""}

Based on this evidence, provide:

1. **ISSUES** - List each problem found with severity (critical/high/medium/low)
2. **PROPOSED FEATURES** - Suggested features to fix each issue
3. **OVERALL ASSESSMENT** - Quality score (0-100) and summary

Format your response as JSON:
```json
{{
  "issues": [
    {{
      "id": "issue-1",
      "severity": "high",
      "category": "error|performance|ux|accessibility",
      "title": "Brief title",
      "description": "Detailed description",
      "evidence": "What in the capture shows this issue",
      "proposed_fix": {{
        "feature_name": "Suggested feature name",
        "description": "What the feature should do",
        "acceptance_criteria": ["AC 1", "AC 2"]
      }}
    }}
  ],
  "overall": {{
    "score": 75,
    "status": "needs_work|acceptable|good",
    "summary": "Brief overall assessment"
  }}
}}
```
"""

    system = """You are a UI quality analyst. Analyze evidence captures and identify issues.
Be specific and actionable. Cite evidence from the capture data.
Always format response as valid JSON."""

    try:
        response = agent.generate(prompt=prompt, system=system, max_tokens=4096)

        # Parse JSON from response
        response_text = response.content
        analysis = None

        # Try to extract JSON from response
        json_match = None
        patterns = [
            r"```json\s*(.*?)\s*```",
            r"```\s*(\{.*?\})\s*```",
            r"(\{[\s\S]*\"issues\"[\s\S]*\})",
        ]

        for pattern in patterns:
            match = re.search(pattern, response_text, re.DOTALL)
            if match:
                json_match = match.group(1)
                break

        if json_match:
            with contextlib.suppress(json.JSONDecodeError):
                analysis = json.loads(json_match)

        if not analysis:
            # Fallback: create structured response from text
            analysis = {
                "issues": [],
                "overall": {
                    "score": 50,
                    "status": "needs_work",
                    "summary": "Could not parse structured response. Raw analysis available.",
                },
                "raw_analysis": response_text,
            }

        # Determine quality status from analysis
        overall = analysis.get("overall", {})
        score = overall.get("score", 50)

        if score >= 80:
            quality_status = "passed"
            confidence = score / 100.0
        elif score >= 50:
            quality_status = "needs_review"
            confidence = score / 100.0
        else:
            quality_status = "failed"
            confidence = score / 100.0

        # Update AI review in database
        evidence_record = get_evidence(project_id, capability_id, criterion_id, version)
        if evidence_record:
            update_ai_review(
                project_id=project_id,
                evidence_id=evidence_record["evidence_id"],
                quality_status=quality_status,
                confidence=confidence,
                ai_evidence=json.dumps(analysis),
                reviewed_by=f"{request.agent}:{agent.get_model_name()}",
            )

        logger.info(
            "agent_review_complete",
            project_id=project_id,
            evidence_id=evidence_id,
            agent=request.agent,
            issues_found=len(analysis.get("issues", [])),
            score=score,
        )

        return {
            "success": True,
            "agent": request.agent,
            "model": agent.get_model_name(),
            "analysis": analysis,
            "quality_status": quality_status,
            "confidence": confidence,
        }

    except RuntimeError as e:
        logger.error("agent_review_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from None


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
    """Get a single evidence record by its database ID.

    Returns the evidence with metadata for regression review.
    """
    from ..storage.connection import get_connection

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
            raise HTTPException(status_code=400, detail="Invalid base64 screenshot data") from None

        # Get next version and create output directory
        version = get_next_version(project_id, request.capability_id, request.criterion_id)
        evidence_base = get_evidence_base_dir(project_id)
        output_dir = evidence_base / request.capability_id / request.criterion_id / f"v{version}"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save screenshot
        screenshot_path = output_dir / "screenshot.png"
        screenshot_path.write_bytes(screenshot_data)

        # Extract client evidence
        client_ev = _extract_client_evidence(request.client_evidence)

        # Create evidence.json with viewport metadata
        evidence_data = {
            "metadata": {
                "url": request.url,
                "capabilityId": request.capability_id,
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
                **client_ev["console"],
                "note": "Client-side evidence from visible error elements",
            },
            "network": {
                "totalRequests": 0,
                "failedRequests": client_ev["network"]["failureCount"],
                "failures": client_ev["network"]["failures"],
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
        current_link = evidence_base / request.capability_id / request.criterion_id / "current"
        if current_link.is_symlink():
            current_link.unlink()
        current_link.symlink_to(f"v{version}")

        # Save to database
        file_size = len(screenshot_data) + len(json.dumps(evidence_data))
        save_evidence(
            project_id=project_id,
            capability_id=request.capability_id,
            criterion_id=request.criterion_id,
            version=version,
            file_path=str(output_dir),
            file_size_bytes=file_size,
        )

        logger.info(
            "viewport_capture_saved",
            project_id=project_id,
            capability_id=request.capability_id,
            criterion_id=request.criterion_id,
            version=version,
            scroll_y=request.scroll_y,
        )

        return {
            "success": True,
            "version": version,
            "capability_id": request.capability_id,
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
            raise HTTPException(status_code=400, detail="Invalid base64 screenshot data") from None

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
        client_ev = _extract_client_evidence(request.client_evidence)
        evidence_data = {
            "metadata": {
                "url": request.url,
                "pageTitle": request.page_title,
                "projectId": project_id,
                "capturedAt": datetime.now(UTC).isoformat(),
                "captureMethod": "client-side-screen-capture-api",
            },
            "console": client_ev["console"],
            "network": {
                "failedRequests": client_ev["network"]["failureCount"],
                "failures": client_ev["network"]["failures"],
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
                    "created_at": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(),
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


# =========================================================================
# Explorer-Driven Evidence Capture Endpoints
# =========================================================================


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
    from ..tasks.evidence_capture import daily_evidence_capture

    try:
        # Run capture async via Celery
        result = daily_evidence_capture.apply_async(
            kwargs={
                "project_id": project_id,
                "scope": request.scope,
                "entry_ids": request.entry_ids,
                "environment": request.environment,
            }
        )

        # For immediate feedback, also run synchronously if small scope
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
    from ..storage.connection import get_connection

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


class EvidenceConfigSuggestion(BaseModel):
    """Suggested evidence configuration for a project."""

    enabled_types: list[str]
    capture_schedule: str
    environments: list[str]
    viewports: list[dict[str, Any]]
    auto_expand_elements: bool
    regression_threshold: float
    ai_review_enabled: bool
    reasoning: str


@router.post("/projects/{project_id}/evidence/config/suggest")
async def suggest_config(
    project_id: str,
) -> EvidenceConfigSuggestion:
    """Analyze project and suggest evidence configuration.

    Looks at:
    - Does project have frontend pages?
    - Does project have API endpoints?
    - Does project have tests?

    Returns suggested configuration.
    """
    from ..storage.connection import get_connection

    # Count entry types
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT entry_type, COUNT(*) as count
            FROM explorer_entries
            WHERE project_id = %s
            GROUP BY entry_type
            """,
            (project_id,),
        )
        entry_counts = {row[0]: row[1] for row in cur.fetchall()}

    has_pages = entry_counts.get("page", 0) > 0
    has_endpoints = entry_counts.get("endpoint", 0) > 0
    has_files = entry_counts.get("file", 0) > 0

    # Build suggestion
    enabled_types = []
    reasoning_parts = []

    if has_pages:
        enabled_types.append("screenshot")
        reasoning_parts.append(f"Found {entry_counts.get('page', 0)} pages - enabling screenshots")

    if has_endpoints:
        enabled_types.append("api_response")
        reasoning_parts.append(
            f"Found {entry_counts.get('endpoint', 0)} endpoints - enabling API responses"
        )

    if has_files:
        reasoning_parts.append(f"Found {entry_counts.get('file', 0)} files")

    if not enabled_types:
        enabled_types = ["screenshot"]
        reasoning_parts.append("No specific entries found - using default screenshot capture")

    return EvidenceConfigSuggestion(
        enabled_types=enabled_types,
        capture_schedule="daily",
        environments=["local"],
        viewports=[
            {"name": "desktop", "width": 1280, "height": 720},
            {"name": "mobile", "width": 390, "height": 844},
        ],
        auto_expand_elements=has_pages,
        regression_threshold=0.05,
        ai_review_enabled=False,
        reasoning=". ".join(reasoning_parts),
    )


class EvidenceConfigUpdate(BaseModel):
    """Request to update evidence configuration."""

    enabled_types: list[str] | None = None
    capture_schedule: str | None = None
    environments: list[str] | None = None
    viewports: list[dict[str, Any]] | None = None
    auto_expand_elements: bool | None = None
    regression_threshold: float | None = None
    ai_review_enabled: bool | None = None


@router.get("/projects/{project_id}/evidence/config")
async def get_evidence_config(project_id: str) -> dict[str, Any]:
    """Get evidence configuration for a project."""
    from ..storage import evidence_config

    config = evidence_config.get_config(project_id)
    return config


@router.put("/projects/{project_id}/evidence/config")
async def update_evidence_config(
    project_id: str,
    request: EvidenceConfigUpdate,
) -> dict[str, Any]:
    """Update evidence configuration for a project."""
    from ..storage import evidence_config

    # Build update dict with only provided fields
    update_data: dict[str, Any] = {}
    if request.enabled_types is not None:
        update_data["enabled_types"] = request.enabled_types
    if request.capture_schedule is not None:
        update_data["capture_schedule"] = request.capture_schedule
    if request.environments is not None:
        update_data["environments"] = request.environments
    if request.viewports is not None:
        update_data["viewports"] = request.viewports
    if request.auto_expand_elements is not None:
        update_data["auto_expand_elements"] = request.auto_expand_elements
    if request.regression_threshold is not None:
        update_data["regression_threshold"] = request.regression_threshold
    if request.ai_review_enabled is not None:
        update_data["ai_review_enabled"] = request.ai_review_enabled

    # Merge with existing config
    current = evidence_config.get_config(project_id)
    merged = {**current, **update_data}

    result = evidence_config.upsert_config(project_id, merged)
    return result


# =========================================================================
# Sub-Element Discovery Endpoints
# =========================================================================


@router.get("/projects/{project_id}/explorer/{entry_id}/sub-elements")
async def get_sub_elements(
    project_id: str,
    entry_id: int,
) -> dict[str, Any]:
    """Get discovered sub-elements for an explorer entry.

    Sub-elements are interactive parts of a page (tabs, accordions, expandable rows)
    that should be captured separately.
    """
    from ..storage import explorer_sub_elements

    elements = explorer_sub_elements.get_elements_for_entry(entry_id)

    return {
        "entry_id": entry_id,
        "sub_elements": [
            {
                "id": el.get("id"),
                "selector": el.get("selector"),
                "element_type": el.get("element_type"),
                "label": el.get("label"),
                "discovered_at": el.get("discovered_at"),
                "last_captured_at": el.get("last_captured_at"),
            }
            for el in elements
        ],
        "count": len(elements),
    }


@router.post("/projects/{project_id}/explorer/{entry_id}/sub-elements/discover")
async def discover_sub_elements(
    project_id: str,
    entry_id: int,
) -> dict[str, Any]:
    """Discover sub-elements for an explorer entry.

    Runs the sub-element discovery script to find tabs, accordions,
    and other interactive elements on the page.
    """
    from ..services.evidence.sub_element_discoverer import discover_elements
    from ..storage.connection import get_connection

    # Get entry URL
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT path, entry_type
            FROM explorer_entries
            WHERE id = %s AND project_id = %s
            """,
            (entry_id, project_id),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Explorer entry not found")

    path, entry_type = row

    if entry_type != "page":
        raise HTTPException(
            status_code=400,
            detail="Sub-element discovery only works for page entries",
        )

    try:
        # Run discovery
        elements = await discover_elements(path)

        # Store discovered elements
        from ..storage import explorer_sub_elements

        for el in elements:
            explorer_sub_elements.upsert_element(
                explorer_entry_id=entry_id,
                selector=el.get("selector", ""),
                element_type=el.get("element_type", "unknown"),
                label=el.get("label"),
            )

        return {
            "success": True,
            "entry_id": entry_id,
            "path": path,
            "elements_found": len(elements),
            "elements": elements,
        }

    except Exception as e:
        logger.error(
            "sub_element_discovery_failed",
            entry_id=entry_id,
            path=path,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e)) from None


# =========================================================================
# Regression Review Endpoints
# =========================================================================


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


@router.get("/projects/{project_id}/evidence/regressions")
async def list_regressions(
    project_id: str,
    status: str | None = Query(None, description="Filter: detected, reviewed, resolved"),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """List regressions for a project.

    Filters by status if provided.
    """
    from ..storage import evidence_regressions
    from ..storage.connection import get_connection

    formatted_regressions: list[dict[str, Any]] = []

    if status == "detected" or status is None:
        # Get unreviewed (detected) regressions
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
        # Get reviewed/resolved regressions
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


class RegressionReviewRequest(BaseModel):
    """Request to review a regression."""

    verdict: str = Field(
        ...,
        description="Verdict: 'accept_change' (intentional) or 'confirm_regression' (bug)",
    )
    notes: str | None = Field(None, description="Optional review notes")


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
    from ..storage import evidence_regressions
    from ..storage.connection import get_connection

    # Validate the regression exists and belongs to this project
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
        # Mark as resolved - the change was intentional
        evidence_regressions.update_status(
            regression_id,
            status="resolved",
            reviewed_by="user",
        )

        # Update the baseline to be the new evidence
        # (The current evidence becomes the new baseline)
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE evidence
                SET is_baseline = true
                WHERE id = %s
                """,
                (row[1],),  # evidence_id
            )
            if row[2]:  # baseline_evidence_id
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
        # Mark as reviewed but not resolved - it's a real bug
        evidence_regressions.update_status(
            regression_id,
            status="reviewed",
            reviewed_by="user",
        )

        # Optionally create a bug task
        from ..tasks.evidence_capture import create_regression_task

        # Get entry path
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
