"""Client-side debug capture endpoints.

Handles browser Screen Capture API uploads for debug captures.
"""

from __future__ import annotations

import base64
import json
import os as _os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()

DEBUG_CAPTURES_BASE = (
    Path(_os.environ.get("SUMMITFLOW_DATA_DIR", "/home/kasadis/summitflow/data")) / "projects"
)


class ClientEvidence(BaseModel):
    """Client-side evidence gathered before screenshot."""

    console: dict[str, Any] = Field(default_factory=dict, description="Console errors/warnings")
    network: dict[str, Any] = Field(default_factory=dict, description="Network failures")


class DebugCaptureRequest(BaseModel):
    """Request for debug viewport capture (no DB entry)."""

    screenshot_base64: str = Field(..., description="Base64-encoded PNG screenshot")
    url: str = Field(..., description="URL of the captured page")
    page_title: str = Field("", description="Page title")
    client_evidence: ClientEvidence | None = Field(
        None, description="Client-side console/network evidence"
    )


def _extract_client_evidence(client_evidence: ClientEvidence | None) -> dict[str, Any]:
    """Extract normalized client evidence dict from ClientEvidence model."""
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


@router.post("/projects/{project_id}/evidence/debug-capture")
async def debug_capture(
    project_id: str,
    request: DebugCaptureRequest,
) -> dict[str, Any]:
    """Save a debug viewport capture without creating a feature entry.

    Saves to: data/projects/{project_id}/debug-captures/{timestamp}.png
    Also maintains: latest.png (symlink to most recent)
    """
    try:
        try:
            screenshot_data = base64.b64decode(request.screenshot_base64)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid base64 screenshot data") from None

        debug_dir = DEBUG_CAPTURES_BASE / project_id / "debug-captures"
        debug_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        screenshot_filename = f"{timestamp}.png"
        screenshot_path = debug_dir / screenshot_filename

        screenshot_path.write_bytes(screenshot_data)

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

        latest_link = debug_dir / "latest.png"
        if latest_link.is_symlink() or latest_link.exists():
            latest_link.unlink()
        latest_link.symlink_to(screenshot_filename)

        latest_json_link = debug_dir / "latest.json"
        if latest_json_link.is_symlink() or latest_json_link.exists():
            latest_json_link.unlink()
        latest_json_link.symlink_to(evidence_filename)

        all_captures = sorted(debug_dir.glob("*.png"))
        all_captures = [p for p in all_captures if p.name not in ("latest.png",)]
        if len(all_captures) > 20:
            for old_capture in all_captures[:-20]:
                old_capture.unlink()
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
    """List recent debug captures for a project."""
    try:
        debug_dir = DEBUG_CAPTURES_BASE / project_id / "debug-captures"
        if not debug_dir.exists():
            return {"captures": [], "count": 0, "latest": None}

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
