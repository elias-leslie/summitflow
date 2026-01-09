"""Evidence configuration and sub-element discovery endpoints.

Configuration management and interactive element discovery for evidence capture.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


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


class EvidenceConfigUpdate(BaseModel):
    """Request to update evidence configuration."""

    enabled_types: list[str] | None = None
    capture_schedule: str | None = None
    environments: list[str] | None = None
    viewports: list[dict[str, Any]] | None = None
    auto_expand_elements: bool | None = None
    regression_threshold: float | None = None
    ai_review_enabled: bool | None = None


@router.post("/projects/{project_id}/evidence/config/suggest")
async def suggest_config(
    project_id: str,
) -> EvidenceConfigSuggestion:
    """Analyze project and suggest evidence configuration.

    Looks at whether the project has frontend pages, API endpoints, or tests.
    Returns suggested configuration.
    """
    from ...storage.connection import get_connection

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


@router.get("/projects/{project_id}/evidence/config")
async def get_evidence_config(project_id: str) -> dict[str, Any]:
    """Get evidence configuration for a project."""
    from ...storage import evidence_config

    config = evidence_config.get_config(project_id)
    return dict(config)


@router.put("/projects/{project_id}/evidence/config")
async def update_evidence_config(
    project_id: str,
    request: EvidenceConfigUpdate,
) -> dict[str, Any]:
    """Update evidence configuration for a project."""
    from ...storage import evidence_config

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

    current = evidence_config.get_config(project_id)
    merged = {**current, **update_data}

    result = evidence_config.upsert_config(
        project_id,
        merged,  # type: ignore[arg-type]
    )
    return dict(result)


@router.get("/projects/{project_id}/explorer/{entry_id}/sub-elements")
async def get_sub_elements(
    project_id: str,
    entry_id: int,
) -> dict[str, Any]:
    """Get discovered sub-elements for an explorer entry.

    Sub-elements are interactive parts of a page (tabs, accordions, expandable rows)
    that should be captured separately.
    """
    from ...storage import explorer_sub_elements

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
    from ...services.evidence.sub_element_discoverer import discover_elements
    from ...storage.connection import get_connection

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
        elements = await discover_elements(path)

        from ...storage import explorer_sub_elements

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
